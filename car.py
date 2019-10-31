import os
from gps import *
from time import *
import time
import threading
import serial
import paho.mqtt.client as mqtt
import math

earthRadius = 6378137
earthCircumference = earthRadius * 2 * math.pi
pixelsPerTile = 256
projectionOriginOffset = earthCircumference / 2
minLat = -85.0511287798
maxLat = 85.0511287798

gpsd = None #seting the global variable
 
#os.system('clear') #clear the terminal (optional)
 
class QuadKey:
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


class GpsPoller(threading.Thread):
  def __init__(self):
    threading.Thread.__init__(self)
    global gpsd #bring it in scope
    gpsd = gps(mode=WATCH_ENABLE) #starting the stream of info
    self.current_value = None
    self.running = True #setting the thread running to true
 
  def run(self):
    global gpsd
    while gpsp.running:
      gpsd.next() #this will continue to loop and grab EACH set of gpsd info to clear the buffer

 
def on_message(client, userdata, message):
  bytes_as_bits = "".join(format(bytee, "08b") for bytee in message.payload)
  preamble = bytes_as_bits[:8]
  m = ser.write(message.payload)  # send the rtcm message in BYTES to the serial p$
  print(m)


if __name__ == '__main__':
  user_mqtt = "userid" #os.environ['MQTT_USER']
  pass_mqtt = "passwd" #os.environ['MQTT_PASS']
  ip_mqtt = "127.0.0.1" #os.environ['MQTT_IP']
  mqtt_port = 1883 #os.environ['MQTT_PORT']
  broker_address = str(ip_mqtt)
  client = mqtt.Client("rover") #create new instance
  client.username_pw_set(username=str(user_mqtt),password=str(pass_mqtt))
  client.on_message = on_message
  print('time to connect')
  client.connect(broker_address, port=int(mqtt_port)) #connect to broker
  print('connection is done')
  # initially subscribe to a dummy topic
  #topic = 'rtcm_3_1_0/#'
  topic ='rtcm_3_1_0/1/2/0/2/0/3/0/2/0/0/2/0/3/1/2/0/2/1/1/3/HELMOND'
  client.subscribe(topic)

  gpsp = GpsPoller() # create the thread
  # socket to which threads is listening and retrieving gps info:
  # ser = serial.Serial('/dev/ttyACM0', 9600)
  ser = serial.Serial('/dev/cu.usbmodem1421', 9600)
  # socket to which gpsd is listening (created by socat)
  # serv = serial.Serial('/dev/pts/9', 9600)
  serv = serial.Serial('/dev/ttys012', 9600)

  try:
    gpsp.start() # start it up
    while True:
      #It may take a second or two to get good GPS data
      nmea = ser.readline()
      serv.write(nmea)
      #print(nmea)
      # get accuracy of gps 
      x = "".join(chr(y) for y in nmea)
      print(x[1:6])
      if str(x[1:6]) == 'GNGSA':
        print(x)
        nmea2 = [y.strip() for y in x.split(",")]
        print('precision   ', nmea2[len(nmea2)-3])
      #serv.write(nmea)
      lat = gpsd.fix.latitude
      lon = gpsd.fix.longitude
      print('latitude    ' , lat)
      print('longitude   ' , lon)
      topic_new = ''
      if math.isnan(lat) == False and math.isnan(lon) == False:
        # old code
        # qk = quadkey.from_geo((lat,lon), 3)
        # quadtree = '/'.join(dot for dot in qk.key)
        qk = QuadKey()
        qk_string = qk.LLToQuadkey(lat, lon, 3)
        quadtree = '/'.join(dot for dot in qk_string)
        topic_new = 'rtcm_3_1_0/' + quadtree + '/#'
        #topic_new = 'rtcm_3_1_0/1/2/0/2/0/3/0/2/0/0/2/0/3/1/2/0/2/1/1/3/HELMOND'
      else:
        topic_new = 'rtcm_3_1_0/1/2/0/#'
      print(topic_new)
      if topic != topic_new:
        client.subscribe(topic_new)
        client.unsubscribe(topic)
        topic = topic_new
      topic_new = ''
      client.loop(10) 
      #time.sleep(1) #set to whatever
 
  except (KeyboardInterrupt, SystemExit): #when you press ctrl+c
    print("\nKilling Thread...")
    gpsp.running = False
    gpsp.join() # wait for the thread to finish what it's doing
  print("Done.\nExiting.")
