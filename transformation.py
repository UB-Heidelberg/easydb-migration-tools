#!/usr/bin/python3
import logging
import logging.config
import sys
import sqlite3
import json

import easydb.migration.transform.job
import easydb.migration.transform.prepare
from easydb.migration.transform.extract import AssetColumn

#execution: ./transform eadb-url source-directory destination-directory --login LOGIN --password PASSWORD || requires source-db named "source.db" in source-directory
###############################################################################

##INSTANZSPEZIFISCHE VARIABLEN
##VOR AUSFÜHRUNG SETZEN!

schema="public"
instanz="unib-heidelberg"
collection_table="workfolder2"
collection_objects_table="workfolder2_bilder"
additional_tranformations=["/usr/local/easydb-migration/easydb-migration-tools/transformations/kum.json"] # List additional transformation dictionary files here (dictionaries must be in JSON format)

###############################################################################


if schema is None or instanz is None or collection_table is None or collection_objects_table is None:
    print('Instanzspezifische Variablen festlegen')
    sys.exit(0)

# setup
job = easydb.migration.transform.job.TransformJob.create_job('INSTANZNAME', easydb.migration.transform.prepare.CreatePolicy.IfNotExists)#creates transform-job named "INSTANZNAME" (change accordingly)


#logger-setup, doesnt have to be changed
standard_formatter = logging.Formatter('%(asctime)s %(levelname)s [%(name)s] %(message)s', '%Y.%m.%d %H:%M:%S')
user_formatter = logging.Formatter('%(message)s')
root_logger = logging.getLogger()
root_logger.setLevel('DEBUG')
user_logger = logging.getLogger('user')
user_logger.setLevel('DEBUG')

console_log = logging.StreamHandler()
console_log.setLevel(logging.DEBUG)
console_log.setFormatter(standard_formatter)
root_logger.addHandler(console_log)

migration_log = logging.FileHandler('{}/migration.log'.format(job.destination_dir))
migration_log.setLevel(logging.DEBUG)
migration_log.setFormatter(standard_formatter)
root_logger.addHandler(migration_log)

user_log = logging.FileHandler('{}/user.log'.format(job.destination_dir))
user_log.setLevel(logging.DEBUG)
user_log.setFormatter(user_formatter)
user_logger.addHandler(user_log)

logging.getLogger('easydb.server').setLevel('WARN')
logging.getLogger('requests').setLevel('WARN')
logging.getLogger('easydb.repository').setLevel('WARN')
logging.getLogger('easydb.migration.transform.source').setLevel('WARN')
logging.getLogger('easydb.migration.transform.prepare').setLevel('INFO')
logging.getLogger('easydb.migration.transform.extract').setLevel('INFO')

def final_touch(tables):
    source_conn = sqlite3.connect(job.source.filename)
    source_c = source_conn.cursor()
    destination_conn = sqlite3.connect(job.destination.filename)
    destination_c = destination_conn.cursor()

    destination_c.execute('DELETE FROM "easydb.ez_user" WHERE login="root"')#Delete root-user, to prevent conflicting unique_user constraint (root is default system-user)
    destination_c.execute('INSERT INTO "easydb.ez_pool" ("__source_unique_id", "name:de-DE") VALUES ("STANDARD", "STANDARD_FALLBACK")')#create FALLBACK-pool for any records that have no pool

    for table in tables:

        if table.get('has_parent'):
            req = 'SELECT fk_father_id, id FROM "' + table["table_from"] +'"'#get parent-ids from source
            for row in source_c.execute(req):
                if row[0]!=None:
                    write = 'UPDATE "{0}" SET __parent_id = '.format(table["table_to"]) + str(row[0]) + ' WHERE __source_unique_id = ' + str(row[1])#set parent-id for lists with hierarchical-ordering
                else:
                    write = 'UPDATE "{0}" SET __parent_id = NULL'.format(table["table_to"]) + ' WHERE __source_unique_id = ' + str(row[1])#set no parent-id
                destination_c.execute(write)
        if table.get('has_pool'):
            destination_c.execute('UPDATE "{0}" SET __pool_id ="STANDARD" WHERE __pool_id = NULL'.format(table["table_to"]))#set pool-id for records that are supposed to be organized in pool, but have no pool assigned
        if table.get('objects_table'):
            destination_c.execute('SELECT object_id, collection_id FROM "easydb.ez_collection__objects"')
            rows = destination_c.fetchall()
            for row in rows:
                query='UPDATE "{0}" SET collection_id = {1} WHERE __source_unique_id = {2}'.format(table["objects_table"], row[1], row[0])
                destination_c.execute(query)
    destination_conn.commit()

#create destination.db
job.prepare()
# Wemm nur eine leere Destion erzeugt werden soll: nächste Zeile aktivieren
#exit()

# transform
tables = []       #list of all tables, a transformation for each table must be appended in the dictionary stile below

##CUSTOM TRANSFORMATIONS
if additional_tranformations:
        for fn in additional_tranformations:
                with open(fn) as fp:
                        add = json.load(fp)
                        for transformation in add:
                                asset_columns_raw = transformation.get('asset_columns_raw')
				# If the transformation contains asset columns, transform the raw data into AssetColumn objects
                                if asset_columns_raw:
                                        transformation['asset_columns'] = [AssetColumn(
						ac.get('instanz'), 
						ac.get('table_from'), 
						ac.get('column_from'), 
						ac.get('table_to'), 
						ac.get('column_to'),
						ac.get('urls')
                                        ) for ac in asset_columns_raw]
                                tables.append(transformation)

for table in tables:
    if table['has_asset']:#Write records with files attached
        job.extract_sql(table['sql'], table['table_to'], asset_columns=table['asset_columns'])

    else:#write assets with no file
        job.extract_sql(table['sql'], table['table_to'])

final_touch(tables)
job.log_times()
