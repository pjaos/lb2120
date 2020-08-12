#!/usr/bin/env python3.8

import  os
import  socket
import  platform
import  json
import  struct
from    time import time, sleep
from    optparse import OptionParser, TitledHelpFormatter, IndentedHelpFormatter
from    threading import Thread, Lock
from    webbot import Browser
from    bs4 import BeautifulSoup

from    open_source_libs.p3lib.uio import UIO
from    open_source_libs.p3lib.pconfig import ConfigManager 
from    open_source_libs.p3lib.boot_manager import BootManager
from    open_source_libs.p3lib.netif import NetIF

class LB2120(Thread):
    """@brief Responsibile for connecting to the Netgear LB2120 4G modem and
              reading stats from it.
       @param uio A UIO instance.
       @param options An optparse OptionParser instance."""

    DEFAULT_ADDRESS     = "192.168.5.1"
    PASSWORD_ENV_VAR    = "NETGEAR_LB2120_PASSWORD"
    POLL_DELAY_SECONDS  = 0.15

    def __init__(self, uio, options):
        """@brief Constructor
           @param uio A UIO instance for user input and output.
           @param options An instance of argparse options.
           """
        Thread.__init__(self)
        self._uio       = uio
        self._options   = options
        
        self._lock      = Lock()
        self._rxp       = None

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
        #web.type('QtV6Dq4s')
        web.click('Sign In')
        web.click(id='session_password')
        startTime = time()
        while True:
            web.go_to("http://{}/index.html#settings/network/status".format(self._options.address))
            content = web.get_page_source()
            now = time()
            elapsedTime = now-startTime
            startTime = now
            self._pollSeconds = elapsedTime

            soup = BeautifulSoup(content, 'html.parser')
            item = soup.body.find('dd', attrs={'class': 'm_wwan_signalStrength_rsrp'})
            self._lock.acquire()
            self._rxp= float(item.string)
            self._uio.debug("4G RXP (dBm): {}".format(self._rxp))
            self._lock.release()
            sleep(LB2120.POLL_DELAY_SECONDS)

    def getRXP(self):
        """@brief Get the RXP received by the modem.
           @return The receive power in dBm."""
        self._lock.acquire()
        rxp = self._rxp
        self._lock.release()
        return rxp

class AYTListener(object):
    """@brief Responsible listening for are you there messages (AYT) from the Android app and
              sending responses back."""

    IP_ADDRESS_KEY           = "IP_ADDRESS"
    OS_KEY                   = "OS"
    UDP_DEV_DISCOVERY_PORT   = 18912
    UDP_RX_BUFFER_SIZE       = 2048
    AYT_KEY                  = "AYT"
    RXP                      = "RXP"
    TCP_PORT_KEY             = "TCP_PORT"

    def __init__(self, uo, options, deviceConfig):
        """@Constructor
            @param uo A UserOutput instance.
            @param options Command line options from OptionParser.
            @param deviceConfig The device configuration instance."""
        self._uio=uo
        self._options=options
        self._deviceConfig=deviceConfig
        self._sock=None

        self._osName = platform.system()
        self._lb2120 = LB2120(self._uio, self._options)
        self._aytReplySocket = None
        self._rxIFName = None

    def _connectToServer(self, serverAddress, tcpPort):
        """@brief Get a socket that is connected to the TCP server.
           @param serverAddress The server address.
           @param tcpPort The TCP socket to connect to on the server.
           @return None"""
        #If not connected then connecto to the server
        if not self._aytReplySocket:
            self._aytReplySocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._aytReplySocket.connect((serverAddress, tcpPort))

    def _sendAYTReply(self, maxRetry=2):
        """@brief Send a reply to the AYT messages (UDP broadcast) on the TCP socket to to the android app on a
                  phone/tablet.
           @param maxRetry The maximum number of sent retry attempts.
           @return None"""
        retryCount = 0
        while True:
            if retryCount >= maxRetry:
                raise Exception("Failed to send AYT reply ({} retry limit reached).".format(maxRetry))
            try:
                #Build reply
                jsonDict = {}
                jsonDict[AYTListener.IP_ADDRESS_KEY] = self._netIF.getIFIPAddress(self._rxIFName)
                jsonDict[AYTListener.OS_KEY] = self._osName
                jsonDict[AYTListener.RXP] = "{}".format(self._lb2120.getRXP())
                jsonDictStr = json.dumps(jsonDict)

                self._uio.debug("%s: %s" % (self.__class__.__name__, jsonDictStr))

                bytesToSend = jsonDictStr.encode()
                bytesLen = len(bytesToSend)
                length = struct.pack('!i', bytesLen)
                self._aytReplySocket.send(length)
                self._aytReplySocket.sendall(jsonDictStr.encode())

                break

            except OSError as error:
                self._uio.errorException()
                self._aytReplySocket.close()
                self._aytReplySocket = None
                self._connectToServer()
                retryCount = retryCount + 1

    def _listener(self):
        """@brief Listen for are you there messages (UDP broadcast) from the android app.
           @return The message received."""
        self._uio.info("Listening on UDP port %d" % (AYTListener.UDP_DEV_DISCOVERY_PORT))

        try:
            while True:
                #Inside loop so we re read config if changed by another instance using --config option.
                jsonDict = self._deviceConfig.getConfigDict()

                #Wait for RX data
                rxData, addressPort = self._sock.recvfrom(AYTListener.UDP_RX_BUFFER_SIZE)

                try:
                    rxDict = json.loads(rxData)
                    if AYTListener.AYT_KEY in rxDict:
                        aytString = rxDict[AYTListener.AYT_KEY]
                        #IF the AYT message matches the one we expect
                        if jsonDict[DeviceConfig.AYT_MSG] == aytString:
                            self._lastAYTMsgTime = time()
                            #The AYT message from the android app contains the TCP port number
                            #of the server to connect to. Check that the message contains the port number.
                            if AYTListener.TCP_PORT_KEY in rxDict:
                                serverTCPPort = rxDict[AYTListener.TCP_PORT_KEY]
                                # Get the name of the interface on which we received the rxData
                                self._rxIFName = self._netIF.getIFName(addressPort[0])
                                self._connectToServer(addressPort[0], serverTCPPort)
                                self._sendAYTReply()

                        elif self._options.debug:
                            self._uio.error("AYT mismatch:")
                            self._uio.info("Expected: {}".format(jsonDict[DeviceConfig.AYT_MSG]) )
                            self._uio.info("Found:    {}".format(aytString) )

                except:
                    pass

        except:
            self._uio.errorException()
            self._uio.info("Shutdown the AYT message listener.")

    def run(self):
        """@brief A blocking method that listens for AYT messages and sends response back to
                  a TCP server on the src address (android app on phone/tablet)."""

        #Start the thread reading the RXP from the LB2120 4G router
        self._lb2120.start()

        self._netIF = NetIF()

        # Open UDP socket to be used for discovering devices
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self._sock.bind(('', AYTListener.UDP_DEV_DISCOVERY_PORT))

        self.initAYTTime()

        try:

            while True:

                self._listener()

                sleep(5)

        finally:
            self.shutDown()

    def shutDown(self):
        """@brief Shutdown the network connection if connected."""
        if self._sock:
            self._sock.close()

    def getSecsSinceAYTMsg(self):
        """@brief Get the number of seconds since we last received an Are You There Message.
           @return The number of seconds since the last AYT messag."""
        seconds = time()-self._lastAYTMsgTime
        return seconds

    def initAYTTime(self):
        """@brief Init the AYT message received time to now."""
        self._lastAYTMsgTime=time()

class DeviceConfig(object):
    """@brief Responsible for managing the configuration used by the ydev application."""

    UNIT_NAME                           = "UNIT_NAME"
    AYT_MSG                             = "AYT_MSG"

    DEFAULT_CONFIG = {
        UNIT_NAME:    "",
        AYT_MSG:      "GET_LB2120_STATUS",
    }

    def __init__(self, uio, configFile):
        """@brief Constructor.
           @param uio UIO instance.
           @param configFile Config file instance."""
        self._uio     = uio

        self._configManager = ConfigManager(self._uio, configFile, DeviceConfig.DEFAULT_CONFIG)
        self._configManager.load()

    def configure(self):
        """@brief configure the required parameters for normal operation."""
        configOK = True
        invalidInitialCharList = ('+','#','/')
        while True:
            self._configManager.inputStr(DeviceConfig.UNIT_NAME, "Enter the name of 4G modem", False)
            unitName = self._configManager.getAttr(DeviceConfig.UNIT_NAME)
            if len(unitName) > 0 and unitName[0] in invalidInitialCharList:
                self._uio.warn("The name of a device may not start with a '%s' character." % (unitName[0]) )
            else:
                break

        self._configManager.inputStr(DeviceConfig.AYT_MSG, "The devices 'Are You There' message text (min 8, max 64 characters)", False)

        if configOK:
            self._configManager.store()
        else:
            self._uio.error("Configuration aborted.")

    def show(self):
        """@brief Show the current configuration parameters."""
        attrList = self._configManager.getAttrList()
        attrList.sort()

        maxAttLen=0
        for attr in attrList:
            if len(attr) > maxAttLen:
                maxAttLen=len(attr)

        for attr in attrList:
            padding = " "*(maxAttLen-len(attr))
            self._uio.info("%s%s = %s" % (attr, padding, self._configManager.getAttr(attr)) )

    def loadConfigQuiet(self):
        """@brief Load the config without displaying a message to the user."""
        self._configManager.load(showLoadedMsg=False)

    def getAttr(self, key):
        """@brief Get an attribute value.
           @param key The key for the value we're after."""

        #If the config file has been modified then read the config to get the updated state.
        if self._configManager.isModified():
            self._configManager.load(showLoadedMsg=False)
            self._configManager.updateModifiedTime()

        return self._configManager.getAttr(key)

    def getConfigDict(self):
        return self._configManager._configDict

#Very simple cmd line template using optparse
def main():
    uio = UIO()

    opts=OptionParser(version="1.0",\
                      description="Read (HTML scrape) the receive power level from a Netgear LB2120 4G modem and send "\
                            "messages including the 4G radio receive power to the Android Aligner App. "\
                            "This program Responsible for responding to AYT messages from the Android Aligner App running "\
                            "on a phone or tablet to send the receive power level of a Netgear LB2120 4G modem back to "\
                            "the Android Aligner App. "\
                            "The Android Aligner App then displays the receive power and outputs a tone that increases "\
                            "in frequency as the receive power increases. "\
                            "You can define the {} environmental variable "\
                            "defining the Netgear LB2120 password to use this program. If not define then the user is\n"
                            "prompted for the LB2120 password on startup.".format(LB2120.PASSWORD_ENV_VAR), formatter=IndentedHelpFormatter())
    opts.add_option("--address",            help="The address of the Netgear LB2120 4G modem (default={}).".format(LB2120.DEFAULT_ADDRESS), default=LB2120.DEFAULT_ADDRESS)
    opts.add_option("--config",             help="Configure persistent configuration options.", action="store_true", default=False)
    opts.add_option("--debug",              help="Enable debugging.", action="store_true", default=False)

    try:
        (options, args) = opts.parse_args()
        uio.enableDebug(options.debug)

        deviceConfig = DeviceConfig(uio, "aligner_cap.cfg")
        if options.config:
            deviceConfig.configure()

        aytListener = AYTListener(uio, options, deviceConfig)
        aytListener.run()

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
