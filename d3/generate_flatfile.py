import logging
import argparse
import os
import pandas as pd

from covid_utils import logs
from covid_utils import connect
from covid_utils import credentials
from load_data import local_config

from d3 import queries

LOCAL = True

class FlatFileGenerator(object):
    def __init__(self, sql, local=True):
        logs.configure_logging('FFGenerator')
        self.logger = logging.getLogger()

        self.file_root = os.path.expanduser(local_config.path_to_this_repo)

        self.sql_key = sql
        self.sql_dict = queries.sql_dict

        self.connect_to_postgres(local)

    def connect_to_postgres(self, local=True):
        self.logger.info("Connecting to postgres..")
        self.pg_creds = credentials.get_postgres_creds(local)
        self.conn = connect.pandas_dbconn(self.pg_creds)
        self.logger.info("Connected to postgres at {}.".format(self.pg_creds['host']))

    def fetch_data(self):
        self.logger.info(f"Running {self.sql_key} query...")
        self.sql_to_run = queries.sql_dict[self.sql_key]

        self.logger.info(f"Using this sql: {self.sql_to_run}")
        self.df = pd.read_sql(self.sql_to_run, self.conn)

    def write_csv(self, output):
        self.logger.info("Forming filename.")
        self.full_output_path = f"{self.file_root}/d3/output/{output}"

        self.logger.info(f"Writing to {self.full_output_path}")
        self.df.to_csv(self.full_output_path, index=False)

        self.logger.info("Done writing file.")


if __name__ == "__main__":

    arguments = argparse.ArgumentParser()
    arguments.add_argument('-s', '--sql', help='sql to use from dict')
    arguments.add_argument('-o', '--output', help='where to write the output file')
    args = arguments.parse_args()

    sql = args.sql
    output = args.output
    if sql is None:
        sql = 'total_deaths_by_state'
        output = 'total_deaths_by_state.csv'

    ff = FlatFileGenerator(sql, LOCAL)
    ff.fetch_data()
    ff.write_csv(output)