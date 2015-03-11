import tornado.auth
import tornado.escape
import tornado.web

import zmq
import pymongo
import bson.json_util as json_util

import sockjs.tornado

from panoptes.utils import logger

@logger.has_logger
class MessagingConnection(sockjs.tornado.SockJSConnection):

    """ Handler for the messaging connection.

    This is the connection between the administrative web interface and
    the running `Panoptes` instance.

    Implemented with sockjs for websockets or long polling.
    """

    def __init__(self, session):
        """ """
        self.session = session

        self.logger.info('Setting up websocket mount control')

        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.REQ)
        self.socket.connect("tcp://localhost:5559")

        self.connections = set()

        self.db = pymongo.MongoClient().panoptes

    def on_open(self, info):
        """ Action to be performed when a client first connects

        We set up a periodic callback to the `_send_stats` method, effectively
        updating the stats on the web site after every delay period. Also send a
        callback to the mount_status for mount monitoring.
        """
        self.logger.info('Setting up websocket mount control for user')

        self.connections.add(self)
        self.send("New connection to mount established")

        self.stats_loop = tornado.ioloop.PeriodicCallback(self._send_stats, 1000)
        self.stats_loop.start()

        self.mount_status_loop = tornado.ioloop.PeriodicCallback(self._send_mount_status, 2000)
        self.mount_status_loop.start()

    def on_message(self, message):
        """ A message received from the client

        The client will be passing commands to our `Panoptes` instance, which
        are captured here and processed. Uses the REQ socket to communicate
        with Observatory broker

        Args:
            message(str):       Message received from client (web). This is
                command that is then passed on to the broker, which is a
                `Panoptes` instance.
        """

        # Send message back to client as confirmation
        # self.send("Message Received: {}".format(message))
        self.logger.info("Message Received: {}".format(message))

        # Send message to Mount
        # self.socket.send_string(message)

        # Get response
        # raw_response = self.socket.recv().decode('ascii')
        raw_response = 'Mount currently disabled'

        response = json_util.dumps({
            'type': 'mount',
            'message': raw_response,
        })

        # Send the response back to the web admins
        self.send(response)

    def on_close(self):
        """ Actions to be performed when web admin client leaves """
        self.connections.remove(self)
        self.stats_loop.stop()
        self.mount_status_loop.stop()

    def _send_stats(self):
        """ Sends the current environment stats to the web admin client

        Called periodically from the `on_open` method, this simply grabs the
        current stats from the mongo db, serializes them to json, and then sends
        to the client.
        """
        data_raw = self.db.sensors.find_one({'status': 'current', 'type': 'environment'})
        data = json_util.dumps({
            'type': 'environment',
            'message': data_raw.get('data'),
        })
        self.send(data)

    def _send_mount_status(self):
        """ Gets the status read off of the mount ands sends to admin

        """
        # Send message to Mount
        self.socket.send_string('get_status')

        # Get response - NOTE: just gets the status code,
        # which is the second charatct [1]. See the iOptron manual
        status_response = self.socket.recv().decode('ascii')[1]

        # Send message to Mount
        self.socket.send_string('current_coords')

        # Get response - NOTE: just gets the status code,
        # which is the second charatct [1]. See the iOptron manual
        coords_response = self.socket.recv().decode('ascii')

        # Send message to Mount
        self.socket.send_string('get_coordinates_altaz')

        # Get response - NOTE: just gets the status code,
        # which is the second charatct [1]. See the iOptron manual
        coords_altaz_response = self.socket.recv().decode('ascii')

        status_map = {
            '0': 'Stopped - Not at zero position',
            '1': 'Tracking (PEC Disabled)',
            '2': 'Slewing',
            '3': 'Guiding',
            '4': 'Meridian Flipping',
            '5': 'Tracking',
            '6': 'Parked',
            '7': 'Home',
        }

        response = json_util.dumps({
            'type': 'mount_status',
            'message': status_map.get(status_response, 'No response from mount'),
            'code': status_response,
            'coords': coords_response,
            'coords_altaz': coords_altaz_response,
        })

        # Send the response back to the web admins
        self.send(response)