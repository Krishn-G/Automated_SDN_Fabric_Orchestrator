from jnpr.junos import Device
import LLDP_Setup
import Topology
import Addressing
import Networks
import Routing_Manual
import os
from dotenv import load_dotenv
load_dotenv()

#=====================================================================================

user     = os.getenv("FABRIC_USER")
password = os.getenv("FABRIC_PASSWORD")

hosts = [v for k, v in sorted(os.environ.items()) if k.startswith("ROUTER_")]
dlist = [Device(host=h, user=user, password=password) for h in hosts]

if_s = ['ge-0/0/1', 'ge-0/0/2', 'ge-0/0/3', 'ge-0/0/4', 'ge-0/0/5']

#=====================================================================================

if __name__ == "__main__":

    LLDP_Setup.LLDP_Setup(dlist, if_s)

    matrix = Topology.Topology(dlist)
    # for row in matrix:
    #     print(row)

    all_routes = Networks.Customer_Routes(dlist)
    # print(all_routes)

    Router_IPs = Addressing.Define_IP(matrix)

    Addressing.Assign_IP(Router_IPs, dlist)

    hops = Routing_Manual.Next_Hops(matrix, Router_IPs, all_routes)
    # print(hops)

    Routing_Manual.Deploy_Routes(hops, dlist)

