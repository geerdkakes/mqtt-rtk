"""
This is heavily based on the NtripPerlClient program written by BKG.
Then heavily based on a unavco original.
"""
#####################################################################################
#
#  Copyright (c) Microsoft Corporation. All rights reserved.
#
# This source code is subject to terms and conditions of the Apache License, Version 2.0. A 
# copy of the license can be found in the License.html file at the root of this distribution. If 
# you cannot locate the  Apache License, Version 2.0, please send an email to 
# ironpy@microsoft.com. By using this source code in any fashion, you are agreeing to be bound 
# by the terms of the Apache License, Version 2.0.
#
# You must not remove this notice, or any other, from this software.
#
#
#####################################################################################

import socket
import sys
import datetime
import base64
import time
import paho.mqtt.client as mqtt
import os
import math
import pyproj
import logging

earthRadius = 6378137
earthCircumference = earthRadius * 2 * math.pi
pixelsPerTile = 256
projectionOriginOffset = earthCircumference / 2
minLat = -85.0511287798
maxLat = 85.0511287798

version=5
useragent="NTRIP JCMBsoftPythonClient/%.1f" % version

# reconnect parameter (fixed values):
factor=2 # How much the sleep time increases with each failed attempt
maxReconnect=1
maxReconnectTime=1200
sleepTime=1 # So the first one is 1 second
maxConnectTime=0

class NtripClient(object):
    def __init__(self, ip_caster, rtcm_port, mountpoint, user_caster, pass_caster, default_quadcode,
                 host=False,
                 height=1212,
                 V2=True,
                 ):
        self.buffer=1024
        self.user_caster= user_caster
        self.pass_caster = pass_caster
        self.port=rtcm_port
        self.caster=ip_caster
        self.mountpoint='/'+mountpoint
        self.height=height
        self.host=host
        self.V2=V2
        self.maxConnectTime=maxConnectTime
        self.bytes_as_bits = ''
        self.socket=None
        self.gps_x = ''
        self.gps_y = ''
        self.gps_z = ''
        self.quadtree = ''
        self.default_quadcode = default_quadcode

    def DegreesToRadians(self,deg):
        return deg * math.pi / 180

    def LLToMeters(self,lat, lon):
        lat = self.DegreesToRadians(lat)
        lon = self.DegreesToRadians(lon)
        sinLat = math.sin(lat)
        x = earthRadius * lon
        y = earthRadius / 2 * math.log((1+sinLat)/(1-sinLat))
        return (x, y)

    def MaxTiles(self,level):
        return 1 << level

    def MetersPerTile(self,level):
        return earthCircumference / self.MaxTiles(level)

    def MetersPerPixel(self,level):
        return self.MetersPerTile(level) / pixelsPerTile

    def MetersToPixel(self,meters, level):
        metersPerPixel = self.MetersPerPixel(level)
        x = (projectionOriginOffset + meters[0]) / metersPerPixel + 0.5
        y = (projectionOriginOffset - meters[1]) / metersPerPixel + 0.5
        return (x, y)

    def LLToPixel(self,lat, lon, level):
        return self.MetersToPixel(self.LLToMeters(lat, lon), level)

    def PixelToTile(self,pixel):
        x = int(pixel[0] / pixelsPerTile)
        y = int(pixel[1] / pixelsPerTile)
        return (x, y)

    def LLToTile(self,lat, lon, level):
        if lat < minLat:
            lat = minLat
        elif lat > maxLat:
            lat = maxLat
        return self.PixelToTile(self.LLToPixel(lat, lon, level))

    def TileToQuadkey(self,tile, level):
        quadkey = ""
        for i in range(level, 0, -1):
            mask = 1 << (i-1)
            cell = 0
            if tile[0] & mask != 0:
                cell += 1
            if tile[1] & mask != 0:
                cell += 2
            quadkey += str(cell)
        return quadkey

    def LLToQuadkey(self,lat, lon, level):
        return self.TileToQuadkey(self.LLToTile(lat, lon, level), level)    
        
        
    def getMountPointString(self):
        userpass = base64.b64encode(bytes(self.user_caster + ':' + self.pass_caster, "utf-8")).decode("ascii")
        mountPointString = "GET %s HTTP/1.1\r\nUser-Agent: %s\r\nAuthorization: Basic %s\r\n" % (self.mountpoint, useragent, userpass)
        
        if self.host or self.V2:
           hostString = "Host: %s:%i\r\n" % (self.caster,self.port)
           mountPointString+=hostString
        if self.V2:
           mountPointString+="Ntrip-Version: Ntrip/2.0\r\n"
        mountPointString+="\r\n"
        logging.debug("mountPointString: " + str(mountPointString))
        return mountPointString

    ### Remove the comments in the following two functions if you want to send an NMEA sentence
    # def getGGAString(self):
    #     now = datetime.datetime.utcnow()
    #     ggaString= "GPGGA,%02d%02d%04.2f,5139.297,N,00532.172,E,1,05,0.19,+00400,M,%5.3f,M,," % \
    #         (now.hour,now.minute,now.second,self.height)
    #     checksum = self.calcultateCheckSum(ggaString)
    #     return "$%s*%s\r\n" % (ggaString, checksum)

    # def calcultateCheckSum(self, stringToCheck):
    #     xsum_calc = 0
    #     for char in stringToCheck:
    #         xsum_calc = xsum_calc ^ ord(char)
    #     return "%02X" % xsum_calc

    def readData(self):
        reconnectTry=1
        sleepTime=1
        if maxConnectTime > 0 :
            EndConnect=datetime.timedelta(seconds=maxConnectTime)
        try:
            while reconnectTry<=maxReconnect:
                found_header=False
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                clientsocket = self.socket.connect_ex((self.caster, self.port))
                logging.debug("clientsocket caster port: " + str(clientsocket) + " " + str(self.caster) + " " + str(self.port))
                if clientsocket==0:
                    sleepTime = 1
                    connectTime=datetime.datetime.now()
                    self.socket.settimeout(10)
                    # Send http request to the caster
                    self.socket.sendall(self.getMountPointString().encode('ascii'))
                    while not found_header:
                        # Get response from the Caster
                        casterResponse=self.socket.recv(4096).decode('ascii')
                        logging.debug("casterResponse" + casterResponse)
                        header_lines = casterResponse.split("\r\n")
                        for line in header_lines:
                            if line=="":
                                if not found_header:
                                    found_header=True
                        for line in header_lines:
                            if line.find("SOURCETABLE")>=0:
                                sys.stderr.write("Mount point does not exist")
                                sys.exit(1)
                            elif line.find("401 Unauthorized")>=0:
                                sys.stderr.write("Unauthorized request\n")
                                sys.exit(1)
                            elif line.find("404 Not Found")>=0:
                                sys.stderr.write("Mount Point does not exist\n")
                                sys.exit(2)
                            ### remove the following comments if you want to transmit the NMEA sentence
                            # elif line.find("ICY 200 OK")>=0:
                            #     #Request was valid
                            #     self.socket.sendall(self.getGGAString().encode('ascii'))
                            # elif line.find("HTTP/1.0 200 OK")>=0:
                            #     #Request was valid
                            #     self.socket.sendall(self.getGGAString().encode('ascii'))
                            # elif line.find("HTTP/1.1 200 OK")>=0:
                            #     #Request was valid
                            #     self.socket.sendall(self.getGGAString().encode('ascii'))

                    data = "Initial data"
                    while data:
                        try:
                            # Reception of RTCM messages from caster in bytes
                            data=self.socket.recv(self.buffer)
                            self.bytes_as_bits = self.bytes_as_bits + ''.join(format(byte, '08b') for byte in data)
                            i = 0
                            while (i+48) < len(self.bytes_as_bits):
                                preamble = self.bytes_as_bits[i:i+8]
                                if hex(int(preamble, 2)) != '0xd3':
                                    logging.warning('error! this is not an rtcm message')
                                    break
                                else:
                                    length = int(self.bytes_as_bits[i+14:i+24],2) # in bytes
                                    length_bits = length*8
                                    end_of_msg = 8 + 6 + 10 + length_bits + i
                                    if (end_of_msg +24) > len(self.bytes_as_bits):
                                        # print('half message')
                                        break
                                    msg_type = int(self.bytes_as_bits[end_of_msg-length_bits:end_of_msg-length_bits+12],2)
                                    logging.debug("received message with type " + str(msg_type))
                                    if int(msg_type) == 1005:
                                        # need to decode the gps coordinates and get the quadkey
                                        self.gps_x = int(self.bytes_as_bits[end_of_msg-length_bits+34:end_of_msg-length_bits+72],2)* 0.0001
                                        self.gps_y = int(self.bytes_as_bits[end_of_msg-length_bits+74:end_of_msg-length_bits+112],2)* 0.0001
                                        self.gps_z = int(self.bytes_as_bits[end_of_msg-length_bits+114:end_of_msg-length_bits+152],2)* 0.0001
                                        ecef = pyproj.Proj(proj='geocent', ellps='WGS84', datum='WGS84')
                                        lla = pyproj.Proj(proj='latlong', ellps='WGS84', datum='WGS84')
                                        lon, lat, alt = pyproj.transform(ecef, lla, self.gps_x, self.gps_y, self.gps_z, radians=False)
                                        # print(lon, lat, alt)
                                        #lat,lon,alt = pm.geodetic2ecef(self.gps_x,self.gps_y,self.gps_z)
                                        qk = self.LLToQuadkey(lat, lon, 20)
                                        # put the slashes between the numbers in the quadkey
                                        self.quadtree = '/'.join(dot for dot in qk)
                                        logging.debug("Found quattree: " + self.quadtree)
                                    if self.quadtree != '':
                                        topic = 'rtcm_3_1_0/' + self.quadtree + self.mountpoint
                                    else: 
                                        logging.warning("using default quadcode, no message type 1005 found yet")
                                        topic = 'rtcm_3_1_0/' + self.default_quadcode + self.mountpoint
                                    logging.debug("publishing data to mqtt")
                                    client.publish(topic, data)
                                    i = end_of_msg + 24
                            self.bytes_as_bits = self.bytes_as_bits[i:]
                    
                            if maxConnectTime :
                                if datetime.datetime.now() > connectTime+EndConnect:
                                    sys.stderr.write("Connection Timed exceeded\n")
                                    sys.exit(0)

                        except socket.timeout:
                            sys.stderr.write('Connection TimedOut\n')
                            data=False
                        except socket.error:
                            sys.stderr.write('Connection Error\n')
                            data=False

                    sys.stderr.write('Closing Connection\n')
                    time.sleep(500)    
                    self.socket.close()
                    self.socket=None

                    if reconnectTry < maxReconnect :
                        sys.stderr.write( "%s No Connection to NtripCaster.  Trying again in %i seconds\n" % (datetime.datetime.now(), sleepTime))
                        time.sleep(sleepTime)
                        sleepTime *= factor
                        if sleepTime>maxReconnectTime:
                            sleepTime=maxReconnectTime
                    reconnectTry += 1
                else:
                    self.socket=None
                    if reconnectTry < maxReconnect :
                        sys.stderr.write( "%s No Connection to NtripCaster.  Trying again in %i seconds\n" % (datetime.datetime.now(), sleepTime))
                        time.sleep(sleepTime)
                        sleepTime *= factor
                        if sleepTime>maxReconnectTime:
                            sleepTime=maxReconnectTime
                    reconnectTry += 1

        except KeyboardInterrupt:
            if self.socket:
                self.socket.close()
            sys.exit()

if __name__ == '__main__':

    # set environmental variables
    ip_caster = os.environ['IP_CASTER']
    rtcm_port = int(os.environ['RTCM_PORT'])
    mountpoint = os.environ['MOUNTPOINT']
    user_caster = os.environ['CASTER_USER']
    pass_caster = os.environ['CASTER_PASS']
    user_mqtt = os.environ['MQTT_USER']
    pass_mqtt = os.environ['MQTT_PASS']
    ip_mqtt = os.environ['MQTT_IP']
    mqtt_port = int(os.environ['MQTT_PORT'])
    default_quadcode = os.environ['DEF_QUADCODE']
    loglevel = os.environ['LOGLEVEL']
    level = 0
    

    if loglevel == 'INFO':
        level = logging.INFO
    elif loglevel == 'WARNING':
        level =logging.WARNING
    elif loglevel == "ERROR":
        level = logging.ERROR
    elif loglevel == "CRITICAL":
        level = logging.CRITICAL
    elif loglevel == 'DEBUG':
        level = logging.DEBUG

    logging.basicConfig(format='%(levelname)s:%(message)s', level = level)
    rootlogger = logging.getLogger(name=None)
    print("loglevel set at: " + logging.getLevelName(rootlogger.level))

    logging.info("starting with following variables:")
    logging.info("IP Caster: " + ip_caster)
    logging.info("RTCM port: " + str(rtcm_port))
    logging.info("Mountpoint: " + mountpoint)
    logging.info("User caster: " + user_caster)
    logging.info("Password caster: " + pass_caster)
    logging.info("User MQTT: " + user_mqtt)
    logging.info("Password MQTT: " + pass_mqtt)
    logging.info("IP MQTT: " + ip_mqtt)
    logging.info("Port MQTT: " + str(mqtt_port))


    

    ##### CONNECT TO MQTT SERVER
    broker_address = str(ip_mqtt)
    client = mqtt.Client("rtk") #create new instance
    client.username_pw_set(username=str(user_mqtt),password=str(pass_mqtt))
    logging.info('Connecting to MQTT')
    client.connect(broker_address, port=int(mqtt_port)) #connect to broker
    logging.info('Connected to MQTT')

    n = NtripClient(ip_caster, rtcm_port, mountpoint, user_caster, pass_caster, default_quadcode)

    logging.info("Initialization complete, starting execution")
    n.readData()

    client.disconnect()
