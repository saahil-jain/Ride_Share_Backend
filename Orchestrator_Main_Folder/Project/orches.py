import pika
import uuid
import flask
import json
from flask import Flask, render_template,jsonify,request,abort,Response
from flask_sqlalchemy import SQLAlchemy
import docker
from kazoo.client import KazooClient
import random
import string
import threading
import math

app = Flask(__name__)

zk = KazooClient(hosts='zoo:2181')
zk.start()
zk.ensure_path("/worker")

characters = string.ascii_letters+string.digits

def scale_container():
    threading.Timer(120.0,scale_container).start()
    
    client = docker.from_env()
    apiclient = docker.APIClient()

    no_of_read_req = {}
    with open('reads_requested.txt','r') as f:
        no_of_read_req = json.load(f)
    
    no_of_containers = {}
    with open('current_containers.txt','r') as f:
        no_of_containers = json.load(f)
    
    containers_required = math.ceil(no_of_read_req['read_req']/20)
    if containers_required == 0:
        containers_required += 1
    containers_present = no_of_containers['no_of_slave_containers']

    no_of_read_req['read_req'] = 0
    with open('reads_requested.txt','w') as f:
        json.dump(no_of_read_req,f)
    
    no_of_containers['no_of_slave_containers'] = containers_required
    with open('current_containers.txt','w') as f:
        json.dump(no_of_containers,f)
    
    if containers_present < containers_required:
        while containers_present != containers_required:
            name_of_container = 'slave' + ''.join(random.choices(characters,k=8))
            client.containers.run(image="ubuntu_slave",command="python3 worker.py",
            environment={"TYPE":"slave","NAME":name_of_container},name=name_of_container,
            links={"ubuntu_rmq_1":"rmq","ubuntu_zoo_1":"zoo"},network="ubuntu_default",detach=True,remove=True)

            containers_present += 1
    
    elif containers_present > containers_required:
        dict_of_slaves = dict()
        for container in client.containers.list():
            if "slave" in container.name or "master" in container.name:
                pid = apiclient.inspect_container(container.id)["State"]["Pid"]
                dict_of_slaves[pid] = container
        
        min_pid = min(dict_of_slaves.keys())
        del dict_of_slaves[min_pid]
        
        while containers_present != containers_required:
            min_pid = min(dict_of_slaves.keys())
            min_container = dict_of_slaves[min_pid]

            del dict_of_slaves[min_pid]

            apiclient.stop(min_container.id)

            containers_present -= 1



class readintodb(object):

    def __init__(self):
        self.connection = pika.BlockingConnection(pika.ConnectionParameters(host='rmq'))

        self.channel = self.connection.channel()

        result = self.channel.queue_declare(queue='', exclusive=True, durable=True)
        self.callback_queue = result.method.queue

        self.channel.basic_consume(
            queue=self.callback_queue,
            on_message_callback=self.on_response,
            )

    def on_response(self, ch, method, props, body):
        if self.corr_id == props.correlation_id:
            self.response = body

    def call(self, n):
        self.response = None
        self.corr_id = str(uuid.uuid4())
        self.channel.basic_publish(
            exchange='',
            routing_key='rpc_queue',
            properties=pika.BasicProperties(
                reply_to=self.callback_queue,
                correlation_id=self.corr_id,
            ),
            body=json.dumps(n))
        while self.response is None:
            self.connection.process_data_events()
        return self.response
    
    def close_connection(self):
        self.connection.close()

@zk.ChildrenWatch('/worker')
def func_watch(children):
    crash_called = {}
    with open('kill_mas_or_slave.txt','r') as f:
        crash_called = json.load(f)
    
    if crash_called['crash'] == 1:
        client = docker.from_env()
        apiclient = docker.APIClient()

        dict_of_containers = dict()
        for container in client.containers.list():
            if "slave" in container.name:
                pid = apiclient.inspect_container(container.id)["State"]["Pid"]
                pid = int(pid)
                dict_of_containers[pid] = container  
        
        if crash_called['master'] == 1:
            min_pid = min(dict_of_containers.keys())
            name_of_new_master = dict_of_containers[min_pid].name
            zk.set('/worker/'+name_of_new_master,b"master")

            name_of_container = 'slave' + ''.join(random.choices(characters,k=8))
            client.containers.run(image="ubuntu_slave",command="python3 worker.py",
            environment={"TYPE":"slave","NAME":name_of_container},name=name_of_container,
            links={"ubuntu_rmq_1":"rmq","ubuntu_zoo_1":"zoo"},network="ubuntu_default",detach=True,remove=True)

        else:
            name_of_container = 'slave' + ''.join(random.choices(characters,k=8))
            client.containers.run(image="ubuntu_slave",command="python3 worker.py",
            environment={"TYPE":"slave","NAME":name_of_container},name=name_of_container,
            links={"ubuntu_rmq_1":"rmq","ubuntu_zoo_1":"zoo"},network="ubuntu_default",detach=True,remove=True)

        crash_called['crash'] = 0
        crash_called['master'] = 0
        with open('kill_mas_or_slave.txt','w') as f:
            json.dump(crash_called,f)




@app.route('/api/v1/db/write',methods=['POST'])
def db_write():
    data = flask.request.json

    connection = pika.BlockingConnection(pika.ConnectionParameters(host='rmq'))
    channel = connection.channel()
    channel.queue_declare(queue='writeQ', durable = True)
    channel.basic_publish(exchange='', routing_key='writeQ', body=data,properties=pika.BasicProperties(delivery_mode=2,))
    connection.close()

    connection = pika.BlockingConnection(pika.ConnectionParameters(host='rmq'))
    channel = connection.channel()
    channel.exchange_declare(exchange='sync',exchange_type='fanout')
    channel.basic_publish(exchange='sync',routing_key='',body=data)
    connection.close()

    connection = pika.BlockingConnection(pika.ConnectionParameters(host='rmq'))
    channel = connection.channel()
    channel.queue_declare(queue='commmands',durable = True)
    channel.basic_publish(exchange='', routing_key='commands', body=data,properties=pika.BasicProperties(delivery_mode=2,))
    connection.close()

    return "Written"
    

@app.route('/api/v1/db/read',methods=['POST'])
def db_read():
    no_of_read_req = {}
    with open('reads_requested.txt','r') as f:
        no_of_read_req = json.load(f)
        no_of_read_req['read_req'] += 1
    
    with open('reads_requested.txt','w') as f:
        json.dump(no_of_read_req,f)

    data = flask.request.json
    data = json.loads(data)
    
    read_client = readintodb()

    response = read_client.call(data)
    read_client.close_connection()
    return response


@app.route('/api/v1/db/clear',methods=['POST'])
def clear_db():
    data = { "table" : "all","method":"none"}
    data = json.dumps(data)

    connection = pika.BlockingConnection(pika.ConnectionParameters(host='rmq'))
    channel = connection.channel()
    channel.queue_declare(queue='writeQ', durable = True)
    channel.basic_publish(exchange='', routing_key='writeQ', body=data,properties=pika.BasicProperties(delivery_mode=2,))
    connection.close()

    connection = pika.BlockingConnection(pika.ConnectionParameters(host='rmq'))
    channel = connection.channel()
    channel.exchange_declare(exchange='sync',exchange_type='fanout')
    channel.basic_publish(exchange='sync',routing_key='',body=data)
    connection.close()

    connection = pika.BlockingConnection(pika.ConnectionParameters(host='rmq'))
    channel = connection.channel()
    channel.queue_declare(queue='commmands',durable = True)
    channel.basic_publish(exchange='', routing_key='commands', body=data,properties=pika.BasicProperties(delivery_mode=2,))
    connection.close()

    return jsonify({}),200

@app.route('/api/v1/crash/master',methods=['POST'])
def crash_master():
    client = docker.from_env()
    apiclient = docker.APIClient()

    dict_of_containers = dict()
    for container in client.containers.list():
        if "slave" in container.name or "master" in container.name:
            pid = apiclient.inspect_container(container.id)["State"]["Pid"]
            pid = int(pid)
            dict_of_containers[pid] = container
    
    master_pid = min(dict_of_containers.keys())
    master_container = dict_of_containers[master_pid]

    apiclient.kill(master_container.id)

    crash_called = {}
    with open('kill_mas_or_slave.txt','r') as f:
        crash_called = json.load(f)
        crash_called['crash'] = 1
        crash_called['master'] = 1
    
    with open('kill_mas_or_slave.txt','w') as f:
        json.dump(crash_called,f)
    
    l = [master_pid]
    
    return jsonify(l),200

@app.route('/api/v1/crash/slave',methods=['POST'])
def crash_slave():
    client = docker.from_env()
    apiclient = docker.APIClient()

    dict_of_containers = dict()
    for container in client.containers.list():
        if "slave" in container.name:
            pid = apiclient.inspect_container(container.id)["State"]["Pid"]
            pid = int(pid)
            dict_of_containers[pid] = container
    
    slave_pid = max(dict_of_containers.keys())
    slave_container = dict_of_containers[slave_pid]

    apiclient.kill(slave_container.id)

    crash_called = {}
    with open('kill_mas_or_slave.txt','r') as f:
        crash_called = json.load(f)
        crash_called['crash'] = 1
        crash_called['master'] = 0
    
    with open('kill_mas_or_slave.txt','w') as f:
        json.dump(crash_called,f)
    
    l = [slave_pid]
    
    return jsonify(l),200



@app.route('/api/v1/worker/list',methods=['GET'])
def getpid():
    client = docker.from_env()
    apiclient = docker.APIClient()
    list_pid = []
    for container in client.containers.list():
        if("master" in container.name or "slave" in container.name):
            pid = apiclient.inspect_container(container.id)["State"]["Pid"]
            list_pid.append(int(pid))
    
    list_pid.sort()
    return jsonify(list_pid)


if __name__=="__main__":
    scale_container()    
    app.run(host = '0.0.0.0')
