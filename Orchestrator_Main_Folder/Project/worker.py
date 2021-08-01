import pika
import flask
import json
from flask import Flask, render_template,jsonify,request,abort,Response
from flask_sqlalchemy import SQLAlchemy
import os
import logging
from kazoo.client import KazooClient

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////app/test.db'
db = SQLAlchemy(app)

logging.basicConfig()

class User(db.Model):
    __tablename__ = 'user'
    username = db.Column(db.String(80), primary_key = True)
    password = db.Column(db.String(40), unique = False, nullable = False)

class Ride(db.Model):
    __tablename__ = 'ride'
    ride_id = db.Column(db.Integer, primary_key = True)
    source = db.Column(db.Integer, nullable = False)
    destination = db.Column(db.Integer, nullable = False)
    timestamp = db.Column(db.String(80), unique = False, nullable = False)
    creator_name = db.Column(db.String(80), unique = False, nullable = False)

class Users_and_Rides(db.Model):
    __tablename__ = 'users_and_rides'
    id = db.Column(db.Integer, primary_key = True)
    ride_id = db.Column(db.Integer, nullable = False)
    username = db.Column(db.String(80), nullable = False)

db.create_all()


def populate_db(list_of_commands):
    connection = pika.BlockingConnection(pika.ConnectionParameters(host='rmq'))
    channel = connection.channel()
    channel.queue_declare(queue='commands',durable = True)    
    while True:
        method_frame, header_frame, body = channel.basic_get('commands')
        if method_frame:
            on_write_req(channel,method_frame,body)
            list_of_commands.append(body)
        else:
            break

    connection.close()

def write_into_command_queue(list_of_commands):
    connection = pika.BlockingConnection(pika.ConnectionParameters(host='rmq'))
    channel = connection.channel()
    channel.queue_declare(queue='commmands',durable = True)
    for i in list_of_commands:
        channel.basic_publish(exchange='', routing_key='commands', body=i,properties=pika.BasicProperties(delivery_mode=2,))
    connection.close()


def on_read_request(channel, method, props, body):
    data = json.loads(body)
    table_chosen = data['table']
    method_used = data['method']
    final_dict = dict()

    if table_chosen == "user":
        if method_used == 'PUT' or method_used == 'DELETE':
            user_name = data['username']
            username_checking = User.query.filter_by(username = user_name).first()
            
            user_details = dict()

            if username_checking is None:
                user_details["empty"] = 1

            else:
                user_details["empty"] = 0
            
            final_dict = user_details
        
        elif method_used == 'GET':
            username_list = User.query.all()
            user_details = dict()

            user_details["list"] = []

            for i in username_list:
                user_details['list'].append(i.username)
            
            final_dict = user_details
        
        elif method_used == "DELETE2":
            username = data['username']
            ride_check = Ride.query.filter_by(creator_name = username).all()
            user_with_ride = dict()
            if len(ride_check) == 0:
                user_with_ride['empty'] = 1
            else:
                user_with_ride['empty'] = 0
            
            final_dict = user_with_ride
    
    elif table_chosen == "ride":
        if method_used == "GET":
            source = data['source']
            dest = data['destination']

            all_rides = Ride.query.filter_by(source = source, destination = dest).all()

            count = 0
            ride_details = dict()
            for i in all_rides:
                ride_details[count] = dict()
                ride_details[count]["rideId"] = i.ride_id
                ride_details[count]["username"] = i.creator_name
                ride_details[count]["timestamp"] = i.timestamp

                count += 1

            final_dict = ride_details
        
        elif method_used == "POST":
            ride_id = data['ride_id']

            ride_details = dict()
            req_ride = Ride.query.filter_by(ride_id = ride_id).first()
            
            if req_ride is None:
                ride_details["empty"] = 1

            else:
                ride_details["empty"] = 0
                ride_details["ride_creator"] = req_ride.creator_name
                ride_details["users_joined"] = []
                ride_details["timestamp"] = req_ride.timestamp

                users_joined = Users_and_Rides.query.filter_by(ride_id = ride_id).all()
                for i in users_joined:
                    ride_details["users_joined"].append(i.username)

            final_dict = ride_details

        elif method_used == "DELETE":
            ride_id = data['ride_id']

            ride_details = dict()
            req_ride = Ride.query.filter_by(ride_id = ride_id).first()

            if req_ride is None:
                ride_details["empty"] = 1

            else:
                ride_details["empty"] = 0

            final_dict = ride_details

        elif method_used == "GET2":
            ride_details = dict()
            req_rides = Ride.query.all()

            ride_details["length"] = len(req_rides)
            
            final_dict = ride_details


    elif table_chosen == "ride and users_and_rides":
        if method_used == "GET":
            ride_id = data['ride_id']

            req_ride = Ride.query.filter_by(ride_id = ride_id).first()

            ride_details = dict()
            if req_ride is None:
                ride_details["empty"] = 1
                
                final_dict = ride_details
            
            else:
                ride_details["empty"] = 0
                ride_details["rideId"] = ride_id
                ride_details["created_by"] = req_ride.creator_name
                ride_details["users"] = []
                ride_details["timestamp"] = req_ride.timestamp
                ride_details["source"] = req_ride.source
                ride_details["destination"] = req_ride.destination

                users_joined = Users_and_Rides.query.filter_by(ride_id = ride_id).all()
                for i in users_joined:
                    ride_details["users"].append(i.username)
                
                final_dict = ride_details

        
    channel.basic_publish(exchange='',routing_key=props.reply_to,
        properties=pika.BasicProperties(correlation_id = \
            props.correlation_id),
        body=json.dumps(final_dict))
    channel.basic_ack(delivery_tag=method.delivery_tag)

def on_write_req(channel,method, body):
    data = json.loads(body)
    table_chosen = data['table']
    method_used = data['method']

    if table_chosen == "user":
        if method_used == "PUT":
            user_name = data['username']
            password = data['password']
            new_user = User(username = user_name,password = password)
            db.session.add(new_user)
            db.session.commit()

        elif method_used == "DELETE":
            user_name = data['username']

            user_being_removed = User.query.filter_by(username = user_name).first()

            db.session.delete(user_being_removed)
            db.session.commit()

            rides_joined = Users_and_Rides.query.filter_by(username = user_name).all()

            if len(rides_joined) != 0:
                for i in rides_joined:
                    db.session.delete(i)
                    db.session.commit()
    
    elif table_chosen == "ride":
        if method_used == "POST":
            ride_creator_username = data['created_by']
            timestamp = data['timestamp']
            source = data['source']
            dest = data['destination']

            new_ride = Ride(source = source, destination = dest,timestamp = timestamp, creator_name = ride_creator_username)
            db.session.add(new_ride)
            db.session.commit()
        
        elif method_used == "DELETE":
            ride_id = data['ride_id']

            ride_dets = Ride.query.filter_by(ride_id = ride_id).first()
            db.session.delete(ride_dets)
            db.session.commit()

            users_joined = Users_and_Rides.query.filter_by(ride_id = ride_id).all()
            if len(users_joined) !=0:
                for i in users_joined:
                    db.session.delete(i)
                    db.session.commit()

    
    elif table_chosen == "users_and_rides":
        if method_used == "POST":
            ride_id = data['ride_id']
            username = data['username']

            new_user_joined = Users_and_Rides(ride_id = ride_id,username = username)
            db.session.add(new_user_joined)
            db.session.commit()
    
    elif table_chosen == "all":
        user_list = User.query.all()

        if(len(user_list) != 0):
            for i in user_list:
                db.session.delete(i)
                db.session.commit()
    

        rides_list = Ride.query.all()

        if(len(rides_list) != 0):
            for i in rides_list:
                db.session.delete(i)
                db.session.commit()
        
        users_joined_rides = Users_and_Rides.query.all()

        if(len(users_joined_rides) != 0):
            for i in users_joined_rides:
                db.session.delete(i)
                db.session.commit()
       
    channel.basic_ack(delivery_tag=method.delivery_tag)


def read_req(channel):    
    channel.queue_declare(queue='rpc_queue')

    channel.basic_qos(prefetch_count=1)
    method_frame, header_frame, body = channel.basic_get('rpc_queue')
    if method_frame:
        on_read_request(channel,method_frame,header_frame,body)

def master_write_req(channel):    
    channel.queue_declare(queue='writeQ',durable = True)

    method_frame, header_frame, body = channel.basic_get('writeQ')
    if method_frame:
        on_write_req(channel,method_frame,body)

def slave_write_req(channel,queue_name):
    method_frame, header_frame, body = channel.basic_get(queue_name)
    if method_frame:
        on_write_req(channel,method_frame,body)

zk = KazooClient(hosts='zoo:2181')
zk.start()

zk.ensure_path("/worker")
container_name = os.environ['NAME']

if not zk.exists("/worker/"+container_name):
    if(os.environ['TYPE'] == "master"):
        zk.create("/worker/"+container_name,b"master",ephemeral=True)
    else:
        zk.create("/worker/"+container_name,b"slave",ephemeral=True)


list_of_commands = []
populate_db(list_of_commands)
if len(list_of_commands) != 0:
    write_into_command_queue(list_of_commands)



while True:
    if(os.environ['TYPE'] == "master"):
        connection = pika.BlockingConnection(pika.ConnectionParameters(host='rmq'))
        channel = connection.channel()
        while True:
            data, stat = zk.get("/worker/"+container_name)
            data = data.decode("utf-8")
            if data != "master":
                os.environ['TYPE'] = "slave"
                connection.close()
                break

            else:
                master_write_req(channel)
    

    elif(os.environ['TYPE'] == "slave"):
        connection = pika.BlockingConnection(pika.ConnectionParameters(host='rmq'))
        channel1 = connection.channel()
        channel2 = connection.channel()

        channel2.exchange_declare(exchange='sync',exchange_type='fanout')

        result = channel2.queue_declare(queue='', exclusive=True)
        queue_name = result.method.queue

        channel2.queue_bind(exchange='sync',queue=queue_name)

        while True:
            data, stat = zk.get("/worker/"+container_name)
            data = data.decode("utf-8")
            if data != "slave":
                os.environ['TYPE'] = "master"
                connection.close()
                break

            else:
                read_req(channel1)
                slave_write_req(channel2,queue_name)
