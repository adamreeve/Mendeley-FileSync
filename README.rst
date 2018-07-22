**Please note that this script no longer works as of Mendeley version 1.19, because the Mendeley database is now encrypted.** See `this issue`_ for more information.

.. _this issue: https://github.com/adamreeve/Mendeley-FileSync/issues/11

Mendeley FileSync
=================

This script stores the location of files associated with Mendeley references
in a text file and then uses that text file to update the files associated with
a document in Mendeley Desktop's database.

It is designed to be used in conjunction with Unison or a service like Dropbox
for people that would prefer not to have to use Mendeley's file storage service
and want to use Mendeley on multiple computers.

Note that you should first synchronise your Mendeley database to get any new references
and then close Mendeley before running this script,
as documents won't be added to any references that have
not first been added to the Mendeley database.

Requirements
------------

This script requires Python >= 2.4 and the Python argparse module.
For versions of Python before 2.5, the pysqlite2 module is required.

For recent versions of Mendeley Desktop, the version of SQLite used by Mendeley
may be incompatible with older versions used by Python. If you get an error about
the database file being encrypted or not a database then you need to update
the version of the SQLite library used by Python. For more information see
https://github.com/adamreeve/Mendeley-FileSync/issues/4.

Usage
-----

The order of steps to use when synchronising your files with this script is important.
First, on the machine where you have added new files:

1) Synchronise Mendeley and close it.

2) Execute this script to update the text file.

Then on the other machine where you want to update Mendeley with the new files:

1) Synchronise Mendeley and close it.

2) Synchronise files using something like Dropbox or manually copying files.
   You need to synchronise both the pdf files and the text file created by
   this script.

3) Execute this script to update the Mendeley database.

4) Open Mendeley and the new files should be added to their references.

When running this script, use::

    ./mendeleyfilesync.py mendeley_database text_file file_path

- ``mendeley_database`` is the path to the sqlite database used by Mendeley, the Mendeley
  website has a FAQ on how to find this file at http://www.mendeley.com/faq/#locate-database.

- ``text_file`` is the location of a file to store reference locations. This should
  be synchronised along with your documents using Unison/Dropbox etc and run on each computer
  after synchronising references in Mendeley Desktop.
  On the first run this file will be created.

- ``file_path`` is the directory where your pdf documents are stored.

Passing the ``--dry-run`` option will just show you what changes would be made but
won't write to the Mendeley database or the text database.
