from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
import broadlink, configparser
import sys, getopt
import time, binascii
import netaddr
import settings
import signal
import socket
import errno
import json
from os import path
from Crypto.Cipher import AES

class Server(HTTPServer):
    def get_request(self):
        result = None
        while result is None:
            try:
                result = self.socket.accept()
                result[0].setblocking(0)
                result[0].settimeout(self.timeout)
            except socket.timeout:
                pass
        return result


class Handler(BaseHTTPRequestHandler):
    def _set_headers(self):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin','*')
        self.end_headers()

    def handle(self):
        self.close_connection = 0

        while not self.close_connection:
            try:
                self.handle_one_request()
            except IOError as e:
                if e.errno == errno.EWOULDBLOCK:
                    self.close_connection=1

    def do_GET(self):
        try:
            if GlobalPassword:
                try:
                    if RestrictAccess and self.client_address[0] not in RestrictAccess:
                        return self.access_denied()
                    return self.messageHandler()
                except NameError:
                    self.password_required()
        except NameError:                   #- No security specified
            self.messageHandler()

    def do_POST(self):
        password = ''
        try:
            content_len = int(self.headers.getheader('content-length', 0))
            password = json.loads(self.rfile.read(content_len))['password'];
        except:
            pass
        try:
            if GlobalPassword and GlobalPassword == password:
                return self.messageHandler()
            else:
                print ("TRY %s != %s" % (GlobalPassword, password))
        except NameError:
                print ("NameError")
                return self.password_required()
        print ("LSE %s != %s" % (GlobalPassword, parameters['password']))
        self.password_required()

    def password_required(self):
        response = "Password required from %s" % self.client_address[0]
        self.wfile.write('''{ "error": "%s" }''' % response)
        print (response)
        self.close_connection = 1
        return False

    def access_denied(self):
        response = "Client %s is not allowed!" % self.client_address[0]
        self.wfile.write('''{ "error": "%s" }''' % response)
        print (response)
        self.close_connection = 1
        return False

    def messageHandler(self):
        if 'favicon' in self.path:
            return False

        self._set_headers()
        paths = self.path.split('/')

        if 'learnCommand' in self.path:
            try:
                if self.client_address[0] not in LearnFrom:
                    print ("Won't learn commands from %s.  Access Denied!" % self.client_address[0])
                    return False
            except NameError:
                pass

            if paths[2] == 'learnCommand':
                deviceName = paths[1]
                commandName = paths[3]
            else:
                commandName = paths[2]
                deviceName = None
            result = learnCommand(commandName,deviceName)
            if result == False:
                response = "Failed: No command learned"
            else:
                response = "Learned: %s" % commandName

        elif 'sendCommand' in self.path:
            if paths[2] == 'sendCommand':
                deviceName = paths[1]
                commandName = paths[3]
            else:
                commandName = paths[2]
                deviceName = None
            if 'on' in commandName or 'off' in commandName:
                status = commandName.rsplit('o', 1)[1]
                realcommandName = commandName.rsplit('o', 1)[0]
                print(status, realcommandName)
                if 'n' in status:
                    setStatus(realcommandName, '1', True)
                elif 'ff' in status:
                    setStatus(realcommandName, '0', True)
            result = sendCommand(commandName, deviceName)
            if result == False:
                response = "Failed: Unknown command"
            else:
                response = "Sent: %s" % commandName

        elif 'getStatus' in self.path:
            if paths[2] == 'getStatus':
                commandName = paths[3]
                deviceName = paths[1]
            else:
                commandName = paths[2]
                deviceName = None
            if 'temp' in commandName:   # Should likely use getSensor instead
                result = getSensor("temperature",deviceName)
                if result == False:
                    response = "Failed: Cannot get temperature"
                else:
                    response = '''{ "temperature": %s } ''' % result
            else:
                status = getStatus(commandName,deviceName)
                if (status):
                    response = status
                else:
                    response = "Failed: Unknown command"

        elif 'setStatus' in self.path:
            if paths[2] == 'setStatus':
                commandName = paths[3]
                deviceName = paths[1]
                status = paths[4]
            else:
                commandName = paths[2]
                deviceName = None
                status = paths[3]
            result = setStatus(commandName, status, deviceName)
            if (result):
                reponse = '''{ "%s": "%s" }''' % (commandName, status)
            else:
                response = "Failed: Unknown command"

        elif 'getSensor' in self.path or 'a1' in self.path:
            if paths[2] == 'getSensor' or paths[2] == 'a1':
                sensor = paths[3]
                deviceName = paths[1]
            else:
                sensor = paths[2]
                deviceName = None
            result = getSensor(sensor, deviceName)
            if result == False:
                reponse = "Failed to get data"
            else:
                if sensor == 'temperature' or sensor == 'humidity':
                    response = '''{ "%s": %s }''' % (sensor, result)
                else:
                    response = '''{ "%s": "%s" }''' % (sensor, result)
        else:
            response = "Failed"
        if "Failed" in response:
            self.wfile.write('''{ "error": "%s" }''' % response)
        elif "Sent" in response:
            self.wfile.write('''{ "ok": "%s" }''' % response)
        else:
            self.wfile.write (response);
        print ("\t"+response)

def sendCommand(commandName,deviceName):
    if deviceName == None:
        device = devices[0]
        serviceName = 'Commands'
    else:
        device = DeviceByName[deviceName];
        serviceName = deviceName + ' Commands'

    deviceKey = device.key
    deviceIV = device.iv

    if settingsFile.has_option(serviceName, commandName):
        commandFromSettings = settingsFile.get(serviceName, commandName)
    elif settingsFile.has_option('Commands', commandName):
        commandFromSettings = settingsFile.get('Commands', commandName)
    else:
        return False

    if commandFromSettings.strip() != '':
        if commandFromSettings.startswith("MACRO "):
            for command in commandFromSettings.strip().split():
                if command.startswith("sleep"):
                    time.sleep(int(command[5:]))
                else:
                    sendCommand(command,deviceName)
            return True
        decodedCommand = binascii.unhexlify(commandFromSettings)
        AESEncryption = AES.new(str(deviceKey), AES.MODE_CBC, str(deviceIV))
        encodedCommand = AESEncryption.encrypt(str(decodedCommand))

        finalCommand = encodedCommand[0x04:]

    try:
        device.send_data(finalCommand)
    except Exception:
        print ("Probably timed out..")
    return True


def learnCommand(commandName, deviceName=None):
    if deviceName == None:
        device = devices[0]
        sectionName = 'Commands'
    else:
        device = DeviceByName[deviceName];
        sectionName = deviceName + ' Commands'

    if OverwriteProtected and settingsFile.has_option(sectionName,commandName):
        print ("Command %s alreadyExists and changes are protected!" % commandName)
        return False

    print ("Waiting %d seconds to capture command" % GlobalTimeout)

    deviceKey = device.key
    deviceIV = device.iv

    device.enter_learning()
    time.sleep(GlobalTimeout)
    LearnedCommand = device.check_data()

    if LearnedCommand is None:
        print('Command not received')
        return False

    AdditionalData = bytearray([0x00, 0x00, 0x00, 0x00])
    finalCommand = AdditionalData + LearnedCommand

    AESEncryption = AES.new(str(deviceKey), AES.MODE_CBC, str(deviceIV))
    decodedCommand = binascii.hexlify(AESEncryption.decrypt(str(finalCommand)))

    broadlinkControlIniFile = open(path.join(settings.applicationDir, 'settings.ini'), 'w')
    if not settingsFile.has_section(sectionName):
        settingsFile.add_section(sectionName)
    settingsFile.set(sectionName, commandName, decodedCommand)
    settingsFile.write(broadlinkControlIniFile)
    broadlinkControlIniFile.close()
    return True


def setStatus(commandName, status, exist=False, deviceName=None):
    if deviceName == None:
        sectionName = 'Status'
    else:
        sectionName = deviceName + ' Status'
    if not settingsFile.has_section(sectionName):
        settingsFile.add_section(sectionName)
    if exist:
        broadlinkControlIniFile = open(path.join(settings.applicationDir, 'settings.ini'), 'w')
        settingsFile.set(sectionName, commandName, status)
        settingsFile.write(broadlinkControlIniFile)
        broadlinkControlIniFile.close()
        return True

    if settingsFile.has_option(sectionName, commandName):
        commandFromSettings = settingsFile.get(sectionName, commandName)
    else:
        return False
    if commandFromSettings.strip() != '':
        broadlinkControlIniFile = open(path.join(settings.applicationDir, 'settings.ini'), 'w')
        settingsFile.set(sectionName, commandName, status)
        settingsFile.write(broadlinkControlIniFile)
        broadlinkControlIniFile.close()
        return True
    else:
        return False


def getStatus(commandName, deviceName=None):
    if deviceName == None:
        sectionName = 'Status'
    else:
        sectionName = deviceName + ' Status'

    if settingsFile.has_option(sectionName,commandName):
        status = settingsFile.get(sectionName, commandName)
        return status
    else:
        return False

def getSensor(sensorName,deviceName=None):
    if deviceName == None:
        device = devices[0]
    else:
        device = DeviceByName[deviceName];
    if "RM" in device.type.upper() and "temp" in sensorName:
        temperature = device.check_temperature()
        if temperature:
            return temperature
    if "A1" in device.type.upper():
        result = device.check_sensors()
        if result:
            return result[sensor]
    return False

def start(server_class=Server, handler_class=Handler, port=8080, listen='0.0.0.0', timeout=1):
    server_address = (listen, port)
    httpd = server_class(server_address, handler_class)
    httpd.timeout = timeout
    print ('Starting broadlink-rest server on %s:%s ...' % (listen,port))
    httpd.serve_forever()


if __name__ == "__main__":

    settingsFile = configparser.ConfigParser()
    settingsFile.optionxform = str
    settingsFile.read(settings.settingsINI)

    global devices
    global DeviceByName
    global GlobalTimeout
    global RestrictedAccess
    global LearnFrom
    global OverwriteProtected
    global GlobalPassword

    # A few defaults
    GlobalTimeout = 2
    DiscoverTimeout = 5
    serverPort = 8080
    Autodetect = False
    OverwriteProtected = True
    listen_address = '0.0.0.0'
    broadcast_address = '255.255.255.255'
    Dev = settings.Dev

    # Override them
    if settingsFile.has_option('General', 'password'):
        GlobalPassword = settingsFile.get('General', 'password').strip()

    if settingsFile.has_option('General', 'serverPort'):
        serverPort = int(settingsFile.get('General', 'serverPort'))

    if settingsFile.has_option('General','serverAddress'):
        listen_address = settingsFile.get('General', 'serverAddress')
        if listen_address.strip() == '':
            listen_address = '0.0.0.0'

    if settingsFile.has_option('General', 'restrictAccess'):
        RestrictAccess = settingsFile.get('General', 'restrictAccess').strip()

    if settingsFile.has_option('General', 'learnFrom'):
        LearnFrom = settingsFile.get('General', 'learnFrom').strip();

    if settingsFile.has_option('General', 'allowOverwrite'):
        OverwriteProtected = False

    if settingsFile.has_option('General','broadcastAddress'):
        broadcast = settingsFile.get('General', 'broadcastAddress')
        if broadcast_address.strip() == '':
            broadcast_address = '255.255.255.255'

    if settingsFile.has_option('General', 'Autodetect'):
        try:
            DiscoverTimeout = int(settingsFile.get('General', 'Autodetect').strip())
        except:
            DiscoverTimeout = 5
        Autodetect = True
        settingsFile.remove_option('General','Autodetect')

    # Device list
    DeviceByName = {}
    if not settings.DevList:
        Autodetect = True

    if Autodetect == True:
        print ("Beginning device auto-detection ... ")
        # Try to support multi-homed broadcast better
        try:
            devices = broadlink.discover(DiscoverTimeout,listen_address,broadcast_address)
        except:
            devices = broadlink.discover(DiscoverTimeout,listen_address)

        broadlinkControlIniFile = open(path.join(settings.applicationDir, 'settings.ini'), 'w')
        for device in devices:
            device.hostname = socket.gethostbyaddr(device.host[0])[0]
            DeviceByName[device.hostname] = device
            if not settingsFile.has_section(device.hostname):
                settingsFile.add_section(device.hostname)
            settingsFile.set(device.hostname,'IPAddress',str(device.host[0]))
            hexmac = ':'.join( [ "%02x" % ( x ) for x in reversed(device.mac) ] )
            settingsFile.set(device.hostname,'MACAddress',hexmac)
            settingsFile.set(device.hostname,'Device',hex(device.devtype))
            settingsFile.set(device.hostname,'Timeout',str(device.timeout * 5))
            settingsFile.set(device.hostname,'Type',device.type.upper())
            device.auth()
            print ("%s: Found %s on %s (%s) type: %s" % (device.hostname, device.type, device.host, hexmac, hex(device.devtype)))
        settingsFile.write(broadlinkControlIniFile)
        broadlinkControlIniFile.close()
    else:
        devices = []
    if settings.DevList:
        for devname in settings.DevList:
            if Dev[devname,'Type'] == 'RM' or Dev[devname,'Type'] == 'RM2':
                device = broadlink.rm((Dev[devname,'IPAddress'], 80), Dev[devname,'MACAddress'], Dev[devname,'Device'])
            if Dev[devname,'Type'] == 'MP1':
                device = broadlink.mp1((Dev[devname,'IPAddress'], 80), Dev[devname,'MACAddress'], Dev[devname,'Device'])
            if Dev[devname,'Type'] == 'SP1':
                device = broadlink.sp1((Dev[devname,'IPAddress'], 80), Dev[devname,'MACAddress'], Dev[devname,'Device'])
            if Dev[devname,'Type'] == 'SP2':
                device = broadlink.sp2((Dev[devname,'IPAddress'], 80), Dev[devname,'MACAddress'], Dev[devname,'Device'])
            if Dev[devname,'Type'] == 'A1':
                device = broadlink.a1((Dev[devname,'IPAddress'], 80), Dev[devname,'MACAddress'], Dev[devname,'Device'])
            if Dev[devname,'Type'] == 'HYSEN':
                device = broadlink.hysen((Dev[devname,'IPAddress'], 80), Dev[devname,'MACAddress'], Dev[devname,'Device'])
            if Dev[devname,'Type'] == 'S1C':
                device = broadlink.S1C((Dev[devname,'IPAddress'], 80), Dev[devname,'MACAddress'], Dev[devname,'Device'])
            if Dev[devname,'Type'] == 'DOOYA':
                device = broadlink.dooya((Dev[devname,'IPAddress'], 80), Dev[devname,'MACAddress'], Dev[devname,'Device'])
            device.timeout = Dev[devname,'Timeout']
            if not devname in DeviceByName:
                device.hostname = devname
                device.auth()
                devices.append(device)
                print ("%s: Found %s on %s (%s)" % (devname, device.type, str(device.host[0]), device.mac))
            DeviceByName[devname] = device

    start(port=serverPort,listen=listen_address,timeout=GlobalTimeout)
