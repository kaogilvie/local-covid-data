import csv
import os
import logging

import psycopg2
from psycopg2.extras import DictCursor
import pandas as pd

from covid_utils import logs
from covid_utils import connect
from covid_utils import credentials

class DataLoader(object):
    def __init__(self, schema='nytimes', env='local'):
        logs.configure_logging(f'{schema.capitalize()}DataLoader')
        self.logger = logging.getLogger()
        self.schema = schema

        self.env = env
        if self.env == 'local':
            from config import local as env_config
        else:
            from config import heroku as env_config
        self.github_info = env_config.github_info
        self.data_repo_path = env_config.data_repo_path
        self.path_to_this_repo = env_config.path_to_this_repo

        self.github_path = self.github_info[schema]['git_file_path']
        self.github_url = self.github_info[schema]['git_url']
        self.file_root = os.path.expanduser(self.path_to_this_repo)

        self.connect_to_postgres()

    def pull_new_github_data(self):
        if os.path.isdir(os.path.expanduser(self.github_path)):
            self.logger.info("Pulling newest data.")
            os.chdir(os.path.expanduser(self.github_path))
            stream = os.popen('git pull')
            self.logger.info(f'{stream.read()}')
            self.logger.info("Newest data pulled.")
        else:
            self.logger.info(f"Directory for {self.schema} doesn't exist yet. Creating and cloning.")
            os.chdir(self.file_root)
            stream = os.popen(f'git clone {self.github_url}')
            self.logger.info(f'{stream.read()}')
            self.logger.info("Newest data cloned.")


    def connect_to_postgres(self):
        self.logger.info(f"Connecting to postgres in env {self.env}..")
        self.pg_creds = credentials.get_postgres_creds(self.env)
        self.cxn = connect.dbconn(self.pg_creds, self.env)
        self.cursor = self.cxn.cursor(cursor_factory=DictCursor)
        self.logger.info("Connected to postgres at {}.".format(self.pg_creds['host']))

    def get_most_recent_date(self, table, date_column='date'):
        self.logger.info(f"Appending new data to {table}. First getting most recent data...")
        self.cursor.execute(f"SELECT max({date_column}) FROM {self.schema}.{table};")
        self.recent_date = self.cursor.fetchall()[0][0]

    def check_table_exists(self, table):
        self.cursor.execute(f"""SELECT EXISTS (
                               SELECT FROM information_schema.tables
                               WHERE  table_schema = '{self.schema}'
                               AND    table_name   = '{table}'
                               );""")
        results = self.cursor.fetchone()
        result = results[0]
        self.logger.info(f"Table already exists: {result}")
        return result

    def fully_load_table(self, data_to_load, data_header, table):
        self.logger.info(f"Initializing full load of {table}...")
        self.cursor.copy_from(data_to_load, f'{self.schema}.{table}', sep=',', null='', columns=data_header)
        self.cxn.commit()

        self.logger.info("Loaded table fully...")
        self.cursor.execute(f"SELECT count(*) FROM {self.schema}.{table};")
        cnt = self.cursor.fetchall()
        self.logger.info(f'...meaning {cnt[0][0]} rows.')

    def load_data(self, table, data_filename, exists=True, date_column='date'):
        self.logger.info("Accessing full reload data..")
        full_filename = os.path.expanduser(f'{self.github_path}/{data_filename}')
        data_to_load = open(full_filename, 'r')
        data_header = next(data_to_load).strip().split(',')
        print(data_header)

        if exists is False:
            self.logger.info("Connecting to Postgres via SQLAlchemy for pandas.")
            self.pd_cxn = connect.pandas_dbconn(self.pg_creds, self.env)
            self.pd_dataframe = pd.read_csv(full_filename)
            sliced_dataframe = self.pd_dataframe.truncate(after=0)
            self.logger.info(f"Creating table using this df template: {sliced_dataframe}")

            self.logger.info("Creating table...")
            sliced_dataframe.to_sql(f'{table}', self.pd_cxn, schema=f'{self.schema}', if_exists='replace', index=False, method='multi')
            self.logger.info("Created table.")

            self.logger.info("Clearing table for full reload.")
            self.cursor.execute(f"""TRUNCATE {self.schema}.{table};""")

            self.fully_load_table(data_to_load, data_header, table)

        else:
            self.get_most_recent_date(table)
            if self.recent_date is None:
                self.fully_load_table(data_to_load, data_header, table)
            else:
                self.logger.info(f"Initializing incremental load of {table} new rows beginning with the day after {self.recent_date}.")

                self.logger.info("Slicing data...")
                full_data_df = pd.read_csv(full_filename)
                insert_df = full_data_df[full_data_df[f'{date_column}'] > str(self.recent_date)]
                self.logger.info(f"Going to append a df of {len(insert_df)} rows using pandas.")

                self.logger.info("Connecting to Postgres via SQLAlchemy for pandas.")
                self.pd_cxn = connect.pandas_dbconn(self.pg_creds, self.env)

                self.logger.info("Appending rows...")
                insert_df.to_sql(f'{table}', self.pd_cxn, schema=f'{self.schema}', if_exists='append', index=False, method='multi')

                self.logger.info("Done appending.")
