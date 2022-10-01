#!/usr/bin/env python3.8

import  os
import  json
import  datetime
import  traceback

from    queue import Queue
from    time import time, sleep
from    optparse import OptionParser
from    webbot import Browser
from    bs4 import BeautifulSoup
from    threading import Thread

from    p3lib.pconfig import ConfigManager
from    p3lib.database_if import DBConfig, DatabaseIF
from    p3lib.uio import UIO

class DBClientConfig(ConfigManager):
    """@brief Responsible for managing the database configuration."""

    CFG_FILENAME            = "4g_usage_db_config.cfg"

    DB_HOST                 = "DB_HOST"
    DB_PORT                 = "DB_PORT"
    DB_USERNAME             = "DB_USERNAME"
    DB_PASSWORD             = "DB_PASSWORD"
    DB_NAME                 = "DB_NAME"
    DB_TABLE_SCHEMA         = "DB_TABLE_SCHEMA"

    DEFAULT_CONFIG = {
        DB_HOST:                    "127.0.0.1",
        DB_PORT:                    3306,
        DB_USERNAME:                "",
        DB_PASSWORD:                "",
        DB_NAME:                    "",
        DB_TABLE_SCHEMA:            ""
    }

    def __init__(self, uio, configFile):
        """@brief Constructor.
           @param uio UIO instance.
           @param configFile Config file instance."""
        super().__init__(uio, configFile, DBClientConfig.DEFAULT_CONFIG, addDotToFilename=False, encrypt=True)
        self._uio     = uio
        self.load()

    def configure(self):
        """@brief configure the required parameters for normal operation."""

        self.inputStr(DBClientConfig.DB_HOST, "Enter the address of the MYSQL database server", False)

        self.inputDecInt(DBClientConfig.DB_PORT, "Enter TCP port to connect to the MYSQL database server", minValue=1024, maxValue=65535)

        self.inputStr(DBClientConfig.DB_USERNAME, "Enter the database username", False)

        self.inputStr(DBClientConfig.DB_PASSWORD, "Enter the database password", False)

        self.inputStr(DBClientConfig.DB_NAME, "Enter the database name to store the data into", False)

        self._uio.info("Example table schema")
        self._uio.info("TIMESTAMP:TIMESTAMP DOWNMBPS:FLOAT(24) UPMBPS:FLOAT(24) TEMPC:FLOAT(24) TEMPCRITICAL:VARCHAR(8)")
        self.inputStr(DBClientConfig.DB_TABLE_SCHEMA, "Enter the database table schema", False)
        #Check the validity of the schema
        tableSchemaString = self.getAttr(DBClientConfig.DB_TABLE_SCHEMA)
        UsageLogger.GetTableSchema(tableSchemaString)
        self._uio.info("Table schema string OK")

        self.store()


class LB2120Stats(object):
    """@brief Responsible for holding the LB2120 parameters that we are interested in."""
    def __init__(self):
        self.sampleTime   = None
        self.downMbps     = None
        self.upMbps       = None
        self.tempC        = None
        self.tempCrticial = None

class LB2120(Thread):
    """@brief Responsibile for connecting to the Netgear LB2120 4G modem and
              reading stats from it.
       @param uio A UIO instance.
       @param options An optparse OptionParser instance."""

    DEFAULT_ADDRESS     = "192.168.5.1"
    PASSWORD_ENV_VAR    = "NETGEAR_LB2120_PASSWORD"
    POLL_DELAY_SECONDS  = 10

    def __init__(self, uio, options, queue):
        """@brief Constructor
           @param uio A UIO instance for user input and output.
           @param options An instance of argparse options.
           @param queue The queue to push LB2120Stats object into.
           """
        Thread.__init__(self)
        self._uio       = uio
        self._options   = options
        self._queue     = queue
        self.running    = False


        self._password = os.environ.get(LB2120.PASSWORD_ENV_VAR)
        if not self._password:
            uio.info("{} environmental variable undefined.".format(LB2120.PASSWORD_ENV_VAR))
            self._password = uio.getInput("Enter the password of the Netgear LB2120 4G router", noEcho=True)

    def run(self):
        """@brief A thread that reads stats from the LB2120 4G modem"""
        web = Browser()
        web.go_to('http://{}/index.html'.format(self._options.address))
        web.click(id='session_password')
        web.type(self._password)
        web.click('Sign In')
        web.click(id='session_password')
        startTime = time()
        lastTotalData = -1
        lastDataRX = -1
        lastDataTX = -1
        self.running = True
        while self.running:
            try:
                web.go_to("http://{}/api/model.json?internalapi=1&x=11228".format( self._options.address ))
                content = web.get_page_source()
                now = time()
                elapsedTime = now-startTime
                startTime = now

                #Remove html text from the response
                jsonContent=content.replace("<html xmlns=\"http://www.w3.org/1999/xhtml\"><head></head><body><pre style=\"word-wrap: break-word; white-space: pre-wrap;\">", "")
                jsonContent=jsonContent.replace("</pre></body></html>", "")

                #Convert json text to a dict
                data = json.loads(jsonContent)

                #Grab the values associated with throughput
                dataRX = int(data['wwan']['dataTransferredRx'])
                dataTX = int(data['wwan']['dataTransferredTx'])
                tempC  = float(data['general']['devTemperature'])
                devTempCritical = data['power']['deviceTempCritical']

                if lastDataRX != -1:
                    if dataRX < lastDataRX:
                        print("<<<<<<<<<< dataRX: {} < {}".format(dataRX, lastDataRX))
                    if dataTX < lastDataTX:
                        print("<<<<<<<<<< dataTX: {} < {}".format(dataTX, lastDataTX))

                    deltaDataRX = dataRX - lastDataRX
                    deltaDataTX = dataTX - lastDataTX

                    downLoadBps = (deltaDataRX/elapsedTime) * 8
                    upLoadBps = (deltaDataTX/elapsedTime) * 8
                    downLoadMBps = float(downLoadBps)/1E6
                    upLoadMBps   = float(upLoadBps/1E6)

                    lb2120Stats = LB2120Stats()
                    lb2120Stats.downMbps = downLoadMBps
                    lb2120Stats.upMbps = upLoadMBps
                    lb2120Stats.tempC = tempC
                    lb2120Stats.tempCrticial = devTempCritical
                    lb2120Stats.sampleTime = datetime.datetime.now()

                    self._queue.put(lb2120Stats)

                #Save the last results for use next time around
                lastDataRX = dataRX
                lastDataTX = dataTX

            except:
                lines = traceback.format_exc().split('\n')
                for l in lines:
                    self._uio.error(l)

            sleep(self._options.psec)

    def shutdown(self):
        """@brief Stop the thread running"""
        self.running = False

class UsageLogger(object):
    """@brief Responsible reading and recording the usage of the 4G internet connection."""

    TIMESTAMP               = "TIMESTAMP"
    TABLE_NAME              = "LB2120_STATS"

    @staticmethod
    def GetTableSchema(tableSchemaString):
        """@brief Get the table schema
           @param tableSchemaString The string defining the database table schema.
           @return A dictionary containing a database table schema."""
        timestampFound=False
        tableSchemaDict = {}
        elems = tableSchemaString.split(" ")
        if len(elems) > 0:
            for elem in elems:
                subElems = elem.split(":")
                if len(subElems) == 2:
                    colName = subElems[0]
                    if colName == UsageLogger.TIMESTAMP:
                        timestampFound=True
                    colType = subElems[1]
                    tableSchemaDict[colName] = colType
                else:
                    raise Exception("{} is an invalid table schema column.".format(elem))
            return tableSchemaDict
        else:
            raise Exception("Invalid Table schema. No elements found.")

        if not timestampFound:
            raise Exception("No {} table column defined.".format(UsageLogger.TIMESTAMP))

    def __init__(self, uo, options, config):
        """@Constructor
            @param uo A UserOutput instance.
            @param options Command line options from OptionParser."""
        self._uio=uo
        self._options=options
        self._config=config
        self._queue = Queue()
        self._lb2120 = LB2120(self._uio, self._options, self._queue)
        self._dataBaseIF = None
        self._addedCount = 0
        self._tableSchema = None

    def _shutdownDBSConnection(self):
        """@brief Shutdown the connection to the DBS"""
        if self._dataBaseIF:
            self._dataBaseIF.disconnect()
            self._dataBaseIF = None

    def _setupDBConfig(self):
        """@brief Setup the internal DB config"""
        self._dataBaseIF                    = None
        self._dbConfig                      = DBConfig()
        self._dbConfig.serverAddress        = self._config.getAttr(DBClientConfig.DB_HOST)
        self._dbConfig.username             = self._config.getAttr(DBClientConfig.DB_USERNAME)
        self._dbConfig.password             = self._config.getAttr(DBClientConfig.DB_PASSWORD)
        self._dbConfig.dataBaseName         = self._config.getAttr(DBClientConfig.DB_NAME)
        self._dbConfig.autoCreateTable      = True
        self._dbConfig.uio                  = self._uio
        self._dataBaseIF                    = DatabaseIF(self._dbConfig)

    def getTableSchema(self):
        """@return the required MYSQL table schema"""
        tableSchemaString = self._config.getAttr(DBClientConfig.DB_TABLE_SCHEMA)
        return UsageLogger.GetTableSchema(tableSchemaString)

    def _connectToDBS(self):
        """@brief connect to the database server."""
        self._shutdownDBSConnection()

        self._setupDBConfig()

        self._dataBaseIF.connect()
        self._uio.info("Connected to database")

        self._tableSchema = self.getTableSchema()
        self._dataBaseIF.ensureTableExists(UsageLogger.TABLE_NAME, self._tableSchema, True)

    def _updateDatabase(self, lb2120Stats):
        """@brief Update the database with the data received from the LB2120 web interface.
           @param lb2120Stats A LB2120Stats instance"""

        if not self._dataBaseIF:
            self._connectToDBS()

        dictToStore = {}
        dictToStore["TIMESTAMP"]=lb2120Stats.sampleTime
        dictToStore["DOWNMBPS"]=lb2120Stats.downMbps
        dictToStore["UPMBPS"]=lb2120Stats.upMbps
        dictToStore["TEMPC"]=lb2120Stats.tempC
        dictToStore["TEMPCRITICAL"]=lb2120Stats.tempCrticial

        self._dataBaseIF.insertRow(dictToStore, UsageLogger.TABLE_NAME, self._tableSchema)
        self._addedCount=self._addedCount + 1
        self._uio.info("{} TABLE: Added count: {}".format(UsageLogger.TABLE_NAME, self._addedCount) )

    def run(self, pollPeriodSeconds=1):
        """@brief A blocking method that reads the internet usage from the LB2120 device
                  and stores the data in a sqlite database."""

        #Start the thread reading the internet usage from the LB2120 4G router
        self._lb2120.start()

        #Check we can connect to the database
        self._connectToDBS()
        try:
            while True:

                try:

                    lb2120Stats = self._queue.get(block=True)

                    self._uio.info("DOWN:          {:.3f} Mbps".format(lb2120Stats.downMbps))
                    self._uio.info("UP:            {:.3f} Mbps".format(lb2120Stats.upMbps))
                    self._uio.info("TEMP:          {:.1f} C".format(lb2120Stats.tempC))
                    self._uio.info("TEMP CRITICAL: {}".format(lb2120Stats.tempCrticial))
                    self._uio.info("SAMPLE TIME:   {}".format(lb2120Stats.sampleTime))

                    self._updateDatabase(lb2120Stats)

                except Exception as ex:
                    self._shutdownDBSConnection()
                    self._lb2120.shutdown()
                    self._lb2120 = LB2120(self._uio, self._options, self._queue)
                    self._lb2120.start()
                    self._connectToDBS()
                    self._uio.error(str(ex))
                    if self._options.debug:
                        raise
                    sleep(errPauseSeconds)

        finally:
            self.shutDown()

    def shutDown(self):
        """@brief Shutdown the db connection if connected."""
        self._shutdownDBSConnection()

#Very simple cmd line template using optparse
def main():
    uio = UIO()

    opts=OptionParser(version="1.0",\
                      description="Read (HTML scrape) the internet usage from a Netgear LB2120 4G modem and record "\
                            "the results in an sqlite database.")
    opts.add_option("--address",  help="The address of the Netgear LB2120 4G modem (default={}).".format(LB2120.DEFAULT_ADDRESS), default=LB2120.DEFAULT_ADDRESS)
    opts.add_option("--psec",     help="The poll period in seconds (default={}).".format(LB2120.POLL_DELAY_SECONDS), type="int", default=LB2120.POLL_DELAY_SECONDS)
    opts.add_option("--config",   help="Configure the database config.", action="store_true", default=False)
    opts.add_option("--debug",    help="Enable debugging.", action="store_true", default=False)

    try:
        (options, args) = opts.parse_args()
        uio.enableDebug(options.debug)

        dbClientConfig = DBClientConfig(uio, DBClientConfig.CFG_FILENAME)

        if options.config:
            dbClientConfig.configure()

        else:
            usageLogger = UsageLogger(uio, options, dbClientConfig)
            usageLogger.run()

    #If the program throws a system exit exception
    except SystemExit:
      pass
    #Don't print error information if CTRL C pressed
    except KeyboardInterrupt:
      pass
    except Exception as error:
     if options.debug:
       raise

     else:
       uio.error(error)

if __name__== '__main__':
    main()
