import flask
from flask import Flask, render_template,jsonify,request,abort,Response
from flask_sqlalchemy import SQLAlchemy
import requests
import json
from datetime import datetime
import re
import csv

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////app/test.db'

areas = dict()
with open('AreaNameEnum.csv') as f:
        dets = csv.reader(f,delimiter = ',')
        line_count = 0
        for row in dets:
                if(line_count==0):
                        line_count+=1
                else:
                        areas[int(row[0])] = row[1]


tv = re.compile(r'\d{2}-\d{2}-\d{4}:\d{2}-\d{2}-\d{2}')

ip = requests.get("http://169.254.169.254/latest/meta-data/public-ipv4").content
ip = ip.decode("utf-8")

url_get_users = 'http://Users-Rides-1846279167.us-east-1.elb.amazonaws.com/api/v1/users'

url_read_rides = 'http://54.152.249.57/api/v1/db/read'
url_write_rides = 'http://54.152.249.57/api/v1/db/write'


@app.before_request
def increase_count():
    if '/api/v1/rides' in request.path:
        data = {}
        with open('count.txt','r') as file_count:
            data = json.load(file_count)
            data['count'] += 1

        with open('count.txt','w') as file_count:
            json.dump(data,file_count)


@app.route('/api/v1/rides',methods=['POST'])
def new_ride():
    try:
        data = flask.request.json
        id_creator = data['created_by']
        timestamp = data['timestamp']
        source = int(data['source'])
        dest = int(data['destination'])

        if not tv.match(timestamp):
            return Response("Timestamp entered in invalid format",status = 400)
        
        now = datetime.now()

        ride_date = datetime.strptime(timestamp, '%d-%m-%Y:%S-%M-%H')
        if ride_date < now:
            return Response("Can't creade ride with a timestamp that has already passed",status = 400)
        
        if source == dest:
            return Response("Source and destination are same",status = 400)

        if(source not in areas.keys() or dest not in areas.keys()):
            ressd = False
        else:
            ressd = True

        user_list = requests.get(url_get_users,headers = {'Origin': ip})
        user_list = json.loads(user_list.text)
        user_list = user_list['list']

        resu = False
        if len(user_list) != 0:
            for i in user_list:
                if i == id_creator:
                    resu = True
                    break
    
        else:
            resu = False

        if ressd and resu:
            ride_dict = {"table" : "ride", "method" : "POST", "created_by" : id_creator, "timestamp" : timestamp, "source" : source, "destination" : dest}
            ride_json = json.dumps(ride_dict)

            requests.post(url_write_rides,json = ride_json)

            return jsonify({}),201
        
        else:
            if not resu:
                return Response("No such user exists",status = 400)
            else:
                return Response("Source or destination invalid",status = 400)
    
    except:
        return Response("Error while providing data",status = 400)


@app.route('/api/v1/rides',methods=['GET'])
def upcoming_rides():
    try:
        source = int(request.args.get('source'))
        destination = int(request.args.get('destination'))
        
        if source not in areas.keys() or destination not in areas.keys():
            return Response("Source or destination invalid",status = 400)
        
        else:
            ride_dict = {"table" : "ride", "method" : "GET", "source" : source, "destination" : destination}
            ride_json = json.dumps(ride_dict)

            ride_results = requests.post(url_read_rides,json = ride_json)
            ride_results = json.loads(ride_results.text)

            if not ride_results:
                return jsonify({}),204
            
            else:
                now = datetime.now()

                l = []

                for i in ride_results.keys():
                    ride_date = ride_results[i]['timestamp']
                    ride_date = datetime.strptime(ride_date, '%d-%m-%Y:%S-%M-%H')

                    if ride_date >= now:
                        l.append(ride_results[i])
                
                if len(l) == 0:
                    return jsonify({}),204
                
                else:
                    return jsonify(l)
        
    except:
        return Response("Error while providing data",status = 400)



@app.route('/api/v1/rides/<ride_id>',methods=['GET'])
def details(ride_id):
    try:
        ride_id = int(ride_id)
        ride_dict = {"table" : "ride and users_and_rides", "method" : "GET", "ride_id" : ride_id}
        ride_json = json.dumps(ride_dict)

        ride_results = requests.post(url_read_rides,json = ride_json)
        ride_results = json.loads(ride_results.text)
        
        if ride_results['empty'] == 1:
            return jsonify({}),204
        else:
            del ride_results['empty']
            
            return jsonify(ride_results)
    
    except:
        return Response("Error while providing data",status = 400)


@app.route('/api/v1/rides/<ride_id>',methods=['POST'])
def join_existing_ride(ride_id):
    try:
        ride_id = int(ride_id)
        data = flask.request.json
        username = data['username']

        ride_dict = {"table" : "ride", "method" : "POST", "ride_id" : ride_id}
        ride_json = json.dumps(ride_dict)

        ride_results = requests.post(url_read_rides,json = ride_json)
        ride_results = json.loads(ride_results.text)

        user_list = requests.get(url_get_users,headers = {'Origin': ip})
        user_list = json.loads(user_list.text)
        user_list = user_list['list']



        if username not in user_list:
            return Response("No user with that username exists",status = 400)
        
        else:
            if ride_results['empty'] == 1:
                return Response("No ride with that id exists",status = 400)
            
            else:
                ride_date = ride_results['timestamp']
                now = datetime.now()
                ride_date = datetime.strptime(ride_date, '%d-%m-%Y:%S-%M-%H')

                if ride_date < now:
                    return Response("Ride has already expired",status = 400)

                if ride_results['ride_creator'] == username:
                    return Response("This user has created the ride",status = 400)

                elif username in ride_results['users_joined']:
                    return Response("This user has already joined ride",status = 400)

                else:
                    user_joining_dict = {"table" : "users_and_rides", "method" : "POST", "ride_id" : ride_id, "username" : username}
                    user_joining_json = json.dumps(user_joining_dict)

                    requests.post(url_write_rides,json = user_joining_json)

                    return jsonify({}),200
    except:
        return Response("Error while providing data",status = 400)


@app.route('/api/v1/rides/<ride_id>',methods=['DELETE'])
def delete_ride(ride_id):
    try:
        ride_id = int(ride_id)
        ride_dict = {"table" : "ride", "method" : "DELETE", "ride_id" : ride_id}
        ride_json = json.dumps(ride_dict)

        ride_results = requests.post(url_read_rides,json = ride_json)
        ride_results = json.loads(ride_results.text)

        if ride_results['empty'] == 1:
            return Response("No ride with that ride_id exists",status = 400)
        
        else:
            ride_and_users_dict = {"table" : "ride", "method" : "DELETE", "ride_id" : ride_id}
            ride_and_users_json = json.dumps(ride_and_users_dict)

            requests.post(url_write_rides,json = ride_and_users_json)

            return jsonify({}),200
    except:
        return Response(status = 400)


#New
@app.route('/api/v1/rides/count',methods=['GET'])
def total_rides():
    try:
        ride_dict = {"table" : "ride", "method" : "GET2"}
        ride_json = json.dumps(ride_dict)

        ride_results = requests.post(url_read_rides,json = ride_json)
        ride_results = json.loads(ride_results.text)

        tot_no_rides = [ride_results["length"]]

        return jsonify(tot_no_rides),200

    except:
        return Response(status = 400)


@app.route('/api/v1/_count',methods=['GET'])
def count_requsts():
    try:
        data = {}
        with open('count.txt','r') as file_count:
            data = json.load(file_count)

        l = [data['count']]
        return jsonify(l),200
    except:
        return Response(status = 400)


@app.route('/api/v1/_count',methods=['DELETE'])
def reset_request():
    try:
        data = {}
        with open('count.txt','r') as file_count:
            data = json.load(file_count)
            data['count'] = 0

        with open('count.txt','w') as file_count:
            json.dump(data,file_count)


        return jsonify({}),200
    except:
        return Response(status = 400)



if __name__=="__main__":
        app.run(host = '0.0.0.0')
