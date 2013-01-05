#!/usr/bin/env python
"""
Synchronise the location of files in the Mendeley database using a relative
base path by storing the locations in a text database that can by synchronised.

Currently ignores files outside of base path.
Just adds new files, doesn't clean deleted files.

Designed to be used with something like Unison or DropBox to synchronise the PDF files.
"""

try:
    import sqlite3
except:
    from pysqlite2 import dbapi2 as sqlite3
import sys,os
from argparse import ArgumentParser

parser = ArgumentParser(prog="mendeleyfilesync.py",description="Synchronise the location of files in the Mendeley database using a relative base path.")
parser.add_argument('mendeley_database',help='Path to the Mendeley sqlite database, eg. "~/.local/share/data/Mendeley Ltd./Mendeley Desktop/you@somewhere.com@www.mendeley.com.sqlite"')
parser.add_argument('text_database',help="Path to the text datbase used to store file locations, eg. ~/.mendeley_files.dat")
parser.add_argument('file_path',help="Base path for local PDF file locations")
parser.add_argument('-d','--dry-run',action='store_const',dest='dryrun',const=True,default=False,help="Print what will happen but don't modify the database")
args = parser.parse_args()

mendeley_database_path=os.path.expanduser(args.mendeley_database)
if not os.path.isfile(mendeley_database_path):
    sys.stderr.write('File '+unicode(mendeley_database_path)+' does not exist\n')
    exit(1)

text_database_path=args.text_database

file_path = os.path.abspath(os.path.expanduser(args.file_path))
if not os.path.isdir(file_path):
    sys.stderr.write(unicode(file_path)+' is not a directory\n')
    exit(1)
#Windows uses file:/// + path, so remove leading / from Linux/Unix paths
if file_path.startswith('/'):
    file_path = file_path[1:]
base_url='file:///'+file_path.replace(os.sep,'/')
if base_url[-1]=='/': base_url=base_url[:-1]

dryrun=args.dryrun

class entry:
    """Store info about a document entry"""
    def __init__(self,*args):
        self.sep=':::' #separator used in the text database
        if len(args)==4:
            self.uuid=unicode(args[0])
            self.key=unicode(args[1])
            self.hash=unicode(args[2])
            self.name=unicode(args[3])
        elif len(args)==1:
            #read from a line in text database
            try:
                (self.uuid,self.key,self.hash,self.name) = unicode(args[0]).strip().split(self.sep)
            except ValueError:
                raise ValueError("Invalid database line: %s" % args[0])
        else:
            raise RuntimeError, "Invalid number of arguments"

    def __unicode__(self):
        #print in format used by text database
        return unicode(self.uuid)+self.sep+\
            unicode(self.key)+self.sep+\
            unicode(self.hash)+self.sep+\
            unicode(self.name)

def remove_base(path):
    """Remove the directory from the file path as stored in the Mendeley database"""
    return path.replace(base_url+"/","")

def get_key(c,id):
    """Get the citation key, eg Smith2011. This is only used to make the text database more readable"""
    c.execute("select citationKey from Documents where id = ?", (id,))
    result = c.fetchone()
    if result:
        return result[0]
    else:
        return ""

def get_uuid(c,id):
    """Get the unique identifier"""
    c.execute("select uuid from Documents where id = ?", (id,))
    result = c.fetchone()
    if result:
        return result[0]
    else:
        return ""

def get_id(c,uuid):
    """Get the document primary key given the uuid"""
    c.execute("select id from Documents where uuid = ?", (uuid,))
    result = c.fetchone()
    if result:
        return result[0]
    else:
        return ""

def get_location(c,hash):
    """Find the file name for a document using the file hash"""
    c.execute("select localUrl from Files where hash = ?", (hash,))
    result = c.fetchone()
    if result:
        return remove_base(result[0])
    else:
        return ""

def get_new_files(afiles,bfiles):
    """Compare a list of files and return a list of the new ones"""
    new_files=[]
    afiles_locations=set([afile.name for afile in afiles])
    for file in bfiles:
        #check if file doesn't exist in other list and make sure it isn't
        #outside the base path
        if file.name not in afiles_locations and file.name.find("file://") < 0:
            new_files.append(file)
    return new_files

def get_different_files(afiles,bfiles):
    """Check if any files have changed"""
    different_files=[]
    adict={}
    for afile in afiles:
        adict[afile.hash]=afile.name
    for bfile in bfiles:
        if bfile.hash in adict:
            if bfile.name != adict[bfile.hash] and bfile.name.find("file://") < 0:
                different_files.append(bfile.name)
    return different_files

def update_mendeley_files(c,files):
    """Update the Mendeley database with any new files from the text database"""
    for file in files:
        #check that document exists
        if get_id(c,file.uuid):
            t=(file.hash,)
            c.execute("select hash from Files where hash = ?",t)
            result = c.fetchone()
            if not result:
                #insert into File table
                t = (file.hash,base_url+"/"+file.name)
                if dryrun:
                    print "Executing:\n"
                    print "insert into Files (hash,localUrl) values (%s,%s)" % t
                else:
                    c.execute("insert into Files (hash,localUrl) values (?,?)",t)
                #insert into DocumentFiles
                t = (get_id(c,file.uuid),file.hash)
                if dryrun:
                    print "Executing:\n"
                    print "insert into Files (hash,localUrl) values (%s,%s)" % t
                else:
                    c.execute("insert into DocumentFiles (documentId,hash,remoteUrl,unlinked,downloadRestricted) values (?,?,'','false','false')",t)
            else:
                sys.stderr.write("Warning: File hash already exists for file "+file.name+".\n")
        else:
            sys.stderr.write("Warning: No Mendeley document for file "+file.name+".\n" \
                    "Perhaps you need to synchronise your Mendeley desktop first.\n")

if __name__=="__main__":
    #open database connection
    connection = sqlite3.connect(mendeley_database_path)
    c = connection.cursor()

    #loop through all files in DocumentFiles table getting file location and citationKey for document
    try:
        c.execute("select documentId,hash from DocumentFiles")
    except sqlite3.OperationalError:
        sys.stderr.write('Error reading the Mendeley database, make sure you specified the path correctly.\n')
        exit(1)
    rows = c.fetchall()
    #doc id, cite key, hash, location
    mendeley_files = [entry(unicode(get_uuid(c,row[0])),unicode(get_key(c,row[0])),row[1],get_location(c,row[1])) for row in rows]

    if(os.path.isfile(text_database_path)):
        #open and read text database
        location_file=open(text_database_path,'r')
        text_files = [entry(line.decode('utf-8')) for line in location_file.readlines()]
        location_file.close()

        #append new files in Mendeley to text database
        new_files = get_new_files(text_files,mendeley_files)
        if len(new_files)==0:
            print "No new files from Mendeley."
        else:
            print "New files from Mendeley:"
            for f in new_files: print f.name
        text_files.extend(new_files)

        #update Mendeley database with new files in text database
        new_files = get_new_files(mendeley_files,text_files)
        if len(new_files)==0:
            print "No new files in text database."
        else:
            print "New files in text database:"
            for f in new_files: print f.name
        update_mendeley_files(c,new_files)

        #write out any conflicts where files exist in both but have different locations
        #so that conflicts can be manually resolved
        different_files = get_different_files(text_files,mendeley_files)
        for file in different_files:
           sys.stderr.write("Conflict: "+file+"\n")

        #write new text file database
        if not dryrun:
            location_file=open(text_database_path,'w')
            for file in text_files:
                location_file.write((unicode(file)+u'\n').encode('utf-8'))
            location_file.close()

        #commit changes and close database connection
        connection.commit()
        c.close()
    else:
        #file doesn't exist yet, create it now and finish
        print "Creating new text database file."
        if dryrun:
            location_file=sys.stdout
        else:
            try:
                location_file=open(text_database_path,'w')
            except:
                sys.stderr.write('Could not open '+text_database_path+' for writing\n')
                exit(1)
        for file in mendeley_files:
            location_file.write((unicode(file)+u'\n').encode('utf-8'))
        if not dryrun: location_file.close()


