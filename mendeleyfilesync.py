#!/usr/bin/env python
"""
Synchronise the location of files in the Mendeley database using a relative
base path by storing the locations in a text database that can by synchronised.

Currently ignores files outside of base path.
Just adds new files, doesn't clean deleted files.
"""

import sqlite3
import sys,os

#parameters
#path to mendeley database file, eg /home/user/.local/share/data/Mendeley Ltd./Mendeley Desktop/email@domain.com@www.mendeley.com.sqlite
mendeley_database_path=''
#path to text database file to store file information, eg /home/user/.mendeley_files.dat
text_database_path=''
#base url for storing PDFs on this machine, must start with file:///, the third / is the root directory
base_url='file:///'

#default behaviour is to run without making any changes unless the update argument is passed
if '--update' in sys.argv:
    dryrun=False
else:
    dryrun=True

class entry():
    """Store info about a document entry"""
    def __init__(self,*args):
        self.sep=':::' #separator used in the text database
        if len(args)==4:
            self.uuid=str(args[0])
            self.key=str(args[1])
            self.hash=str(args[2])
            self.name=str(args[3])
        elif len(args)==1:
            #read from a line in text database
            (self.uuid,self.key,self.hash,self.name) = str(args[0]).strip().split(self.sep)
        else:
            raise RuntimeError, "Invalid number of arguments"

    def __str__(self):
        #print in format used by text database
        return str(self.uuid)+self.sep+\
            str(self.key)+self.sep+\
            str(self.hash)+self.sep+\
            str(self.name)

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
            sys.stderr.write("Warning: Document doesn't exist for file "+file.name+".\n")

if __name__=="__main__":
    #open database connection
    connection = sqlite3.connect(mendeley_database_path)
    c = connection.cursor()

    #loop through all files in DocumentFiles table getting file location and citationKey for document
    c.execute("select documentId,hash from DocumentFiles")
    rows = c.fetchall()
    #doc id, cite key, hash, location
    mendeley_files = [entry(str(get_uuid(c,row[0])),str(get_key(c,row[0])),row[1],get_location(c,row[1])) for row in rows]

    if(os.path.isfile(text_database_path)):
        #open and read text database
        location_file=open(text_database_path,'r')
        text_files = [entry(line) for line in location_file.readlines()]
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
           sys.stderr.write("Conflict: "+file.name+"\n")

        #write new text file database
        if not dryrun:
            location_file=open(text_database_path,'w')
            for file in text_files:
                location_file.write(str(file)+'\n')
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
            location_file=open(text_database_path,'w')
        for file in mendeley_files:
            location_file.write(str(file)+'\n')
        if not dryrun: location_file.close()


