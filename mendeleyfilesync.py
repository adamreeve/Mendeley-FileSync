#!/usr/bin/env python
"""
Synchronise the location of files in the Mendeley database using a
relative base path by storing the locations in a text database that
can by synchronised.

Currently ignores files outside of the base path.
It will also only add new files, it won't clean deleted files.

Designed to be used with something like Unison or DropBox to
synchronise the PDF files.
"""


from argparse import ArgumentParser
import os
import sys
import urllib
from itertools import ifilter
try:
    import sqlite3
except:
    from pysqlite2 import dbapi2 as sqlite3


def main():
    # Parse command line arguments
    parser = ArgumentParser(
            prog='mendeleyfilesync.py',
            description="Synchronise the location of files in the Mendeley "
                        "database using a relative base path.")
    parser.add_argument('mendeley_database',
            help='Path to the Mendeley sqlite database, eg. '
            '"~/.local/share/data/Mendeley Ltd./Mendeley Desktop/'
            'you@somewhere.com@www.mendeley.com.sqlite"')
    parser.add_argument('text_database',
            help="Path to the text datbase used to store file locations, "
                 "eg. ~/.mendeley_files.dat")
    parser.add_argument('file_path',
            help="Directory used to store PDF files")
    parser.add_argument('-d', '--dry-run',
            action='store_const', dest='dry_run',
            const=True, default=False,
            help="Display changes that would be made but don't actually "
                 "modify the database")
    parser.add_argument('-f', '--force-update',
            action='store_const', dest='force_update',
            const=True, default=False,
            help="Replace file path in Mendeley with path from the text "
                 "database when there is a conflict")
    args = parser.parse_args()

    # Check path to Mendeley database file
    if not os.path.isfile(args.mendeley_database):
        sys.stderr.write('File "%s" does not exist\n' % args.mendeley_database)
        exit(1)

    # Check path to directory where PDFs are stored
    if not os.path.isdir(args.file_path):
        sys.stderr.write('"%s" is not a directory\n' % args.file_path)
        exit(1)

    with MendeleyDB(
            args.mendeley_database,
            args.file_path,
            args.dry_run) as mendeley_db:
        run_synchronisation(
                mendeley_db, args.text_database,
                args.dry_run, args.force_update)


class MendeleyDB(object):
    """
    An interface to the Mendeley database
    """

    def __init__(self, path, file_path, dry_run=False):
        self.path = path
        self.base_url = directory_to_url(file_path)
        self.dry_run = dry_run

    def __enter__(self):
        """
        Open the database connection
        """

        self.connection = sqlite3.connect(self.path)
        self.cursor = self.connection.cursor()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """
        Close the database connection
        """

        self.connection.commit()
        self.cursor.close()

    def execute_unsafe(self, statement, values=()):
        """
        Execute an SQL statement that may alter data

        If dry_run is set, print the statement and don't execute anything.
        This is useful for debugging or just for peace of mind.
        """

        if self.dry_run:
            s = statement
            for v in values:
                s = s.replace('?', '"%s"' % str(v), 1)
            print("Executing: %s" % s)
        else:
            return self.cursor.execute(statement, values)

    def get_document(self, id):
        """
        Get a document using the document id
        """

        self.cursor.execute(
                "SELECT uuid, citationKey FROM Documents WHERE id = ?", (id, ))
        result = self.cursor.fetchone()
        if result:
            uuid, citation_key = result
            if citation_key is None:
                citation_key = ""
        else:
            raise KeyError("Could not find document with id %s" % id)
        return (uuid, citation_key)

    def document_id(self, uuid):
        """
        Get the db primary key for a document from the uuid
        """

        self.cursor.execute(
                "SELECT id FROM Documents WHERE uuid = ?", (uuid, ))
        result = self.cursor.fetchone()
        if result:
            return result[0]
        else:
            raise KeyError("Couldn't find document with uuid %s" % uuid)

    def get_file_name(self, hash):
        """
        Find the file name from the file hash
        """

        self.cursor.execute(
                "SELECT localUrl FROM Files WHERE hash = ?", (hash, ))
        result = self.cursor.fetchone()
        if result:
            full_path = result[0]
            return full_path.replace(self.base_url + u'/', '')
        else:
            raise KeyError("Couldn't find file with hash %s" % hash)

    def document_files(self):
        """
        Return all files associated with documents
        """

        self.cursor.execute("SELECT documentId, hash FROM DocumentFiles")
        for document_id, file_hash in self.cursor.fetchall():
            doc_uuid, doc_citation_key = self.get_document(document_id)
            file_name = self.get_file_name(file_hash)
            # Some files are not stored locally, so the file name is not set
            if file_name:
                yield DocumentFile(
                        doc_uuid, doc_citation_key, file_hash, file_name)

    def add_file(self, document_file):
        """
        Add the file to the database and attach it to the document
        """

        # Check document exists in Mendeley database
        try:
            document_id = self.document_id(document_file.uuid)
        except KeyError:
            sys.stderr.write(
                    "Warning: No Mendeley document for file %s.\n"
                    "Perhaps you need to synchronise your Mendeley "
                    "desktop client first.\n" % document_file.name)
            return

        # Check file doesn't already exist
        self.cursor.execute(
                "SELECT hash FROM Files WHERE hash = ?",
                (document_file.hash, ))
        result = self.cursor.fetchone()
        if result:
            sys.stderr.write("Warning: File hash already exists "
                    "for file %s.\n" % document_file.name)
            return

        # Insert file
        file_url = u'/'.join((self.base_url, document_file.name))
        self.execute_unsafe(
            "INSERT INTO Files (hash, localUrl) VALUES (?, ?)",
            (document_file.hash, file_url))

        # Link file to document
        self.execute_unsafe(
            "INSERT INTO DocumentFiles "
            "(documentId, hash, remoteUrl, unlinked, downloadRestricted) "
            "VALUES (?, ?, '', 'false', 'false')",
            (document_id, document_file.hash))

    def update_file(self, document_file):
        """
        Update the file path for an existing file
        """

        file_url = u'/'.join((self.base_url, document_file.name))
        self.execute_unsafe(
                "UPDATE Files SET localUrl=? WHERE hash=?",
                (file_url, document_file.hash))


class DocumentFile(object):
    """
    A file associated with a reference document
    for storing in the text database
    """

    # Separator used in the text database
    sep = u':::'

    def __init__(self, uuid, key, hash, name):
        # uuid and key represent document
        # there may be multiple files with the same document
        self.uuid = uuid
        self.key = key
        # hash and name represent file
        self.hash = hash
        self.name = name

    @classmethod
    def from_text(cls, line):
        """
        Initialise a new entry from the text representation
        """

        try:
            (uuid, key, hash, name) = line.strip().split(cls.sep)
        except ValueError:
            raise ValueError("Invalid database line: %s" % line)

        return cls(uuid, key, hash, name)

    def text_entry(self):
        """
        Return a string representing the entry in the
        format used by text database
        """

        return self.sep.join((self.uuid, self.key, self.hash, self.name))

    def sort_key(self):
        """
        Key used to sort document files in the text database
        """

        if self.key:
            return self.key.lower()
        else:
            return self.name.lower()


def directory_to_url(path):
    """
    Convert a directory path to a URL format
    """

    path = os.path.abspath(path)
    # Remove leading slash so Linux and Windows paths both
    # don't have a slash, which can then be added
    if path.startswith('/'):
        path = path[1:]
    # Make sure separators are forward slashes
    path = path.replace(os.sep, '/')
    if path.endswith('/'):
        path = path[:-1]
    # Url encode special characters
    url = u'file:///' + urllib.quote(path, safe='/:').decode('ascii')

    return url


def relative_file(file):
    """
    Check that a file is within the PDF storage directory
    """

    # If it is, the base path will have been removed
    return file.name.find(u'file://') < 0


def get_new_files(afiles, bfiles):
    """
    Compare a list of files and return a list of the new ones
    """

    afile_hashes = set(afile.hash for afile in afiles)

    # Check that the file doesn't exist in the other set and make sure it
    # also isn't outside the base path, in which case it's ignored
    new_files = (file for file in bfiles if
            file.hash not in afile_hashes)

    return ifilter(relative_file, new_files)


def get_different_files(afiles, bfiles):
    """
    Check if any file names have changed
    """

    a_file_names = dict((file.hash, file.name) for file in afiles)

    # Find files with same hash but named differently
    different_files = (
            (file, a_file_names[file.hash]) for file in bfiles if
            file.hash in a_file_names and
            file.name != a_file_names[file.hash])

    return different_files


def run_synchronisation(mendeley_db, text_database_path,
        dry_run=False, force_update=False):
    """
    Synchronise updates between the Mendeley database and
    text file database
    """

    mendeley_entries = set(mendeley_db.document_files())

    if os.path.isfile(text_database_path):
        with open(text_database_path, 'r') as text_db_file:
            text_db_entries = set(
                    DocumentFile.from_text(line.decode('utf-8'))
                    for line in text_db_file)
    else:
        # Assume this is the first run and the text database
        # hast not yet been created
        print("Creating new text database file.")
        text_db_entries = set()

    # Add new files from Mendeley to the text database
    new_files = set(get_new_files(text_db_entries, mendeley_entries))
    if new_files:
        print("New files from Mendeley:")
        for f in new_files:
            print(f.name)
            text_db_entries.add(f)
    else:
        print("No new files from Mendeley.")

    # Update Mendeley database with new files from the text database
    new_files = set(get_new_files(mendeley_entries, text_db_entries))
    if new_files:
        print("New files from the text database:")
        for f in new_files:
            print(f.name)
            mendeley_db.add_file(f)
    else:
        print("No new files from the text database.")

    # Write out any conflicts where files exist in both but have
    # different locations, so that conflicts can be manually resolved,
    # or override the file path in Mendeley if force_update is set
    different_files = get_different_files(mendeley_entries, text_db_entries)
    for different_file, conflicting_name in different_files:
        if force_update:
            sys.stderr.write(
                    "Forcing update: %s to %s\n" %
                    (conflicting_name, different_file.name))
            mendeley_db.update_file(different_file)
        else:
            sys.stderr.write(
                    "Conflict: %s, %s\n" %
                    (conflicting_name, different_file.name))

    # Write updated text database file
    text_db_lines = ((file.text_entry() + u'\n').encode('utf-8')
            for file in sorted(text_db_entries, key=lambda f: f.sort_key()))

    if not dry_run:
        with open(text_database_path, 'w') as text_db_file:
            for line in text_db_lines:
                text_db_file.write(line)
    else:
        print("Text file:")
        for line in text_db_lines:
            sys.stdout.write(line)


if __name__ == '__main__':
    main()
