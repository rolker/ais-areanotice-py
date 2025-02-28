#!/usr/bin/env python
from __future__ import print_function

__author__    = 'Kurt Schwehr'
__version__   = '$Revision: 4799 $'.split()[1]
__revision__  = __version__ # For pylint
__date__ = '$Date: 2006-09-25 11:09:02 -0400 (Mon, 25 Sep 2006) $'.split()[1]
__copyright__ = '2009'
__license__   = 'LGPL v3'
__contact__   = 'kurt at ccom.unh.edu'

__doc__ ='''
Trying to do a more sane design for AIS BBM message.

http://vislab-ccom.unh.edu/~schwehr/papers/2010-IMO-SN.1-Circ.289.pdf

WARNING: The IMO Circ is not byte aligned.  ITU 1371-3, Annex 2,
1.2.3.1 says that the message must be byte aligned.  And Annex 2,
3.3.7 says "Unused bits in the last byte should be set to zero in
order to preserve byte boundary."  That that refers to the VDL data.
It is unclear if that is after the bit stuffing and if those extra
bits should be returned back into into the NMEA message.  The code here
has the option to byte align the resulting bits in get_aivdm.

@requires: U{Python<http://python.org/>} >= 2.6
@requires: U{epydoc<http://epydoc.sourceforge.net/>} >= 3.0.1
@requires: U{lxml<http://codespeak.net/lxml/lxmlhtml.html>} >= 2.0
@requires: U{shapely<http://pypi.python.org/pypi/Shapely/>}
@requires: U{BitVector<http://pypi.python.org/pypi/BitVector/>}
@requires: U{pyproj<http://code.google.com/p/pyproj/>}
@requires: U{geojson<http://pypi.python.org/pypi/geojson/>}

@license: GPL v3
@undocumented: __doc__
@since: 2009-Jun-01
@status: under development
@organization: U{CCOM<http://ccom.unh.edu/>} 

@todo: handle polyline and polygons that span multiple subareas
@todo: handle text that spans adjacent subareas
'''

# http://blog.lucanatali.it/2006/12/nmea-checksum-in-python.html

import sys
#from decimal import Decimal
import datetime, time
from operator import xor # for checksum

import operator
#from math import *
import math

from pyproj import Proj
import shapely.geometry
#import geojson

import lxml
from lxml.html import builder as E

from BitVector import BitVector

import binary, aisstring
import Queue
import re

import geodesic

next_sequence=1
'Track the next value to use for multiline nmea messages'


SUB_AREA_SIZE = 87
'87 Bits for IMO Circ 289 rather than the 90 for USCG and Nav 55 version'

iso8601_timeformat = '%Y-%m-%dT%H:%M:%SZ'

# ais_nmea_regex_str = r'''[!$](?P<talker>AI)(?P<stringType>VD[MO])
# ,(?P<total>\d?)
# ,(?P<sen_num>\d?)
# ,(?P<seq_id>[0-9]?)
# ,(?P<chan>[AB])
# ,(?P<body>[;:=@a-zA-Z0-9<>\?\'\`]*)
# ,(?P<fill_bits>\d)\*(?P<checksum>[0-9A-F][0-9A-F])'''
# '''Ignore USCG metadata'''

# With USCG metadata
ais_nmea_regex_str = r'''^!(?P<talker>AI)(?P<string_type>VD[MO])
,(?P<total>\d?)
,(?P<sen_num>\d?)
,(?P<seq_id>[0-9]?)
,(?P<chan>[AB]?)
,(?P<body>(?P<msg_id>[;:=@a-zA-Z0-9<>\?\'\`])[;:=@a-zA-Z0-9<>\?\'\`]*)
,(?P<fill_bits>\d)\*(?P<checksum>[0-9A-F][0-9A-F])
(  
  (,S(?P<slot>\d*))
  | (,s(?P<s_rssi>\d*))
  | (,d(?P<signal_strength>[-0-9]*))
  | (,t(?P<t_recver_hhmmss>(?P<t_hour>\d\d)(?P<t_min>\d\d)(?P<t_sec>\d\d.\d*)))
  | (,T(?P<time_of_arrival>[^,]*))
  | (,x(?P<x_station_counter>[0-9]*))
  | (,(?P<station>(?P<station_type>[rbB])[a-zA-Z0-9_]*))
)*
(,(?P<time_stamp>\d+([.]\d+)?))?
'''

# msg_id is only valid on the first message in a group

ais_nmea_regex = re.compile(ais_nmea_regex_str,  re.VERBOSE)

kml_head = '''<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2" xmlns:gx="http://www.google.com/kml/ext/2.2" xmlns:kml="http://www.opengis.net/kml/2.2" xmlns:atom="http://www.w3.org/2005/Atom">
<Document>
'''
'Beginning of a KML file for visualization'

kml_tail = '''</Document>
</kml>
'''
'Finish a kml file'

def kml_lookat(time_begin=None, time_end=None,
               x=None, y=None,
               alt=None, heading=None,
               tilt=None, range=None):
    '''Create a LookAt KML entry'''

    o = ['<LookAt>'] # build a list of strings to include
    if time_begin is not None or time_end is not None:
        o.append('<gx:TimeSpan>')
        if time_begin is not None: o.append('<begin>'+time_begin+'</begin>')
        if time_end   is not None: o.append('<end>'  +time_end  +'</end>')
        o.append('</gx:TimeSpan>')
    if x is not None: o.append('<longitude>%s</longitude>' % (x,))
    if y is not None: o.append('<latitude>%s</latitude>' % (y,))
    if alt is not None: o.append('<altitude>%s</altitude>' % (alt,))
    if range is not None: o.append('<range>%s</range>' % (range,))
    o.append('</LookAt>')
    return '\n'.join(o)


def lon_to_utm_zone(lon):
    return int(( lon + 180 ) / 6) + 1

iso8601_timeformat = '%Y-%m-%dT%H:%M:%SZ'
'''ISO time format for NetworkLinkControl strftime
@see: U{KML Tutorial<http://code.google.com/apis/kml/documentation/kml_21tutorial.html#updates>}
'''


nmea_talkers = {
    'PS':'FIX: something to do with Class B AIS',
    # http://yachtelectronics.blogspot.com/2011/02/srt-proprietary-ais-commands.html
    'AG':'Autopilot - General',
    'AI':'Automatic Identification System',
    'AP':'Autopilot - Magnetic',
    'CC':'Computer - Programmed Calculator (outdated)',
    'CD':'Communications - Digital Selective Calling (DSC)',
    'CM':'Computer - Memory Data (outdated)',
    'CS':'Communications - Satellite',
    'CT':'Communications - Radio-Telephone (MF/HF)',
    'CV':'Communications - Radio-Telephone (VHF)',
    'CX':'Communications - Scanning Receiver',
    'DE':'DECCA Navigation (outdated)',
    'DF':'Direction Finder',
    'EC':'Electronic Chart Display & Information System (ECDIS)',
    'EP':'Emergency Position Indicating Beacon (EPIRB)',
    'ER':'Engine Room Monitoring Systems',
    'GP':'Global Positioning System (GPS)',
    'HC':'Heading - Magnetic Compass',
    'HE':'Heading - North Seeking Gyro',
    'HN':'Heading - Non North Seeking Gyro',
    'II':'Integrated Instrumentation',
    'IN':'Integrated Navigation',
    'LA':'Loran A (outdated)',
    'LC':'Loran C',
    'MP':'Microwave Positioning System (outdated)',
    'OM':'OMEGA Navigation System (outdated)',
    'OS':'Distress Alarm System (outdated)',
    'RA':'RADAR and/or ARPA',
    'SD':'Sounder, Depth',
    'SN':'Electronic Positioning System, other/general',
    'SS':'Sounder, Scanning',
    'TI':'Turn Rate Indicator',
    'TR':'TRANSIT Navigation System',
    'VD':'Velocity Sensor, Doppler, other/general',
    'DM':'Velocity Sensor, Speed Log, Water, Magnetic',  # Should this be VD?
    'VW':'Velocity Sensor, Speed Log, Water, Mechanical',
    'WI':'Weather Instruments ',
    'YC':'Transducer - Temperature (outdated)',
    'YD':'Transducer - Displacement, Angular or Linear (outdated)',
    'YF':'Transducer - Frequency (outdated)',
    'YL':'Transducer - Level (outdated)',
    'YP':'Transducer - Pressure (outdated)',
    'YR':'Transducer - Flow Rate (outdated)',
    'YT':'Transducer - Tachometer (outdated)',
    'YV':'Transducer - Volume (outdated)',
    'YX':'Transducer',
    'ZA':'Timekeeper - Atomic Clock',
    'ZC':'Timekeeper - Chronometer',
    'ZQ':'Timekeeper - Quartz',
    'ZV':'Timekeeper - Radio Update, WWV or WWVH',
}
'''Prefixes for NMEA strings that say where a message originated. http://gpsd.berlios.de/NMEA.txt
BBM messages may require having EC as the prefix.
'''

notice_type = {
    'cau_mammans': 0,# Rats, they got rid of the "NOT observed", but I will still use it that way
    'cau_mammals_not_obs': 0,
    'cau_mammals_reduce_speed': 1,
    'cau_mammals_stay_clear': 2,
    'cau_mammals_report_sightings': 3,
    'cau_habitat_reduce_speed': 4,
    'cau_habitat_stay_clear': 5,
    'cau_habitat_no_fishing_or_anchoring': 6,
    'cau_derelicts': 7, 
    'cau_congestion': 8,
    'cau_event': 9,
    'cau_divers': 10,
    'cau_swimmers': 11,
    'cau_dredging': 12,
    'cau_surveying': 13,
    'cau_underwater_ops': 14,
    'cau_seaplane_ops': 15,
    'cau_nets_in_water': 16,
    'cau_cluster_fishing_vessels': 17,
    'cau_fairway_closed': 18,
    'cau_harbor_closed': 19,
    'cau_risk_see_text': 20,
    'cau_auv_ops': 21,
    'env_storm_front': 23,
    'env_ice': 24,
    'env_storm': 25,
    'env_wind': 26,
    'env_waves': 27,
    'env_restr_vis': 28,
    'env_currents': 29,
    'env_icing': 30,
    'res_no_fishing': 32,
    'res_no_anchoring': 33,
    'res_entry_approval_req': 34,
    'res_no_entry': 35,
    'res_military_ops': 36,
    'res_firing_danger': 37,
    'res_drifting_mines': 38,
    'anc_open': 40,
    'anc_closed': 41,
    'anc_prohibited': 42,
    'anc_deep_draft': 43,
    'anc_Shallow': 44,
    'anc_transfer': 45,
    'sec_1': 56,
    'sec_2': 57,
    'sec_3': 58,
    'dis_adrift': 64,
    'dis_sinking': 65,
    'dis_abandoning': 66,
    'dis_requ_medical': 67,
    'dis_flooding': 68,
    'dis_fire_explosion': 69,
    'dis_grounding': 70,
    'dis_collision': 71,
    'dis_listing_capsizing': 72,
    'dis_under_assault': 73,
    'dis_person_overboard': 74,
    'dis_sar': 75,
    'dis_pollution': 76,
    'inst_contact_vts_here': 80,
    'inst_contact_port_admin_here': 81,
    'inst_do_not_proceed_beyond_here': 82,
    'inst_await_instr_here': 83,
    'proc_to_location': 84,
    'clearance_granted': 85,
    'info_pilot_boarding': 88,
    'info_icebreaker_staging': 89,
    'info_refuge': 90,
    'info_pos_icebreakers': 91,
    'info_pos_response_units': 92,
    'vts_active_target': 93,
    'suspicious_vessel': 94,
    'request_non_distress_assistance':95,
    'chart_sunken_vessel': 96,
    'chart_Submerged_obj': 97,
    'chart_Semi_submerged_obj': 98,
    'chart_shoal': 99,
    'chart_shoal_due_North': 100,
    'chart_Shoal_due_North': 100,
    'chart_Shoal_due_East': 101,
    'chart_Shoal_due_South': 102,
    'chart_Shoal_due_West': 103,
    'chart_channel_obstruction': 104,
    'chart_reduced_vert_clearance': 105,
    'chart_bridge_closed': 106,
    'chart_bridge_part_open': 107,
    'chart_bridge_fully_open': 108,
    'report_of_icing': 112,
    # USCG version has 113 "REport from ship: Intended route"
    'report_of_see_text': 114,
    'route_rec_route': 120,
    'route_alt_route': 121,
    'route_rec_through_ice': 122,
    'other_see_text': 125,
    'cancel_area_notice': 126,
    'undefined': 127,
    0: 'Caution Area: Marine mammals NOT observed',  # This is slightly different than in IMO 289
    #0: 'Caution Area: Marine mammal habitat',  # IMO 289 version - going to ignore their text.
    1: 'Caution Area: Marine mammals in area - Reduce Speed',
    2: 'Caution Area: Marine mammals in area - Stay Clear',
    3: 'Caution Area: Marine mammals in area - Report Sightings',
    4: 'Caution Area: Protected Habitat - Reduce Speed',
    5: 'Caution Area: Protected Habitat - Stay Clear',
    6: 'Caution Area: Protected Habitat - No fishing or anchoring',
    7: 'Caution Area: Derelicts (drifting objects)',
    8: 'Caution Area: Traffic congestion',
    9: 'Caution Area: Marine event',
    10: 'Caution Area: Divers down',
    11: 'Caution Area: Swim area',
    12: 'Caution Area: Dredge operations',
    13: 'Caution Area: Survey operations',
    14: 'Caution Area: Underwater operation',
    15: 'Caution Area: Seaplane operations',
    16: 'Caution Area: Fishery - nets in water',
    17: 'Caution Area: Cluster of fishing vessels',
    18: 'Caution Area: Fairway closed',
    19: 'Caution Area: Harbor closed',
    20: 'Caution Area: Risk - define in free text field',
    21: 'Caution Area: Underwater vehicle operation',
    22: 'Reserved',
    23: 'Storm front (line squall)',
    24: 'Env. Caution Area: Hazardous sea ice',
    25: 'Env. Caution Area: Storm warning (storm cell or line of storms)',
    26: 'Env. Caution Area: High wind',
    27: 'Env. Caution Area: High waves',
    28: 'Env. Caution Area: Restricted visibility (fog, rain, etc)',
    29: 'Env. Caution Area: Strong currents',
    30: 'Env. Caution Area: Heavy icing',
    31: 'Reserved',
    32: 'Restricted Area: Fishing prohibited',
    33: 'Restricted Area: No anchoring.',
    34: 'Restricted Area: Entry approval required prior to transit',
    35: 'Restricted Area: Entry prohibited',
    36: 'Restricted Area: Active military OPAREA',
    37: 'Restricted Area: Firing - danger area.',
    38: 'Restricted Area: Drifting Mines',
    39: 'Reserved',
    40: 'Anchorage Area: Anchorage open',
    41: 'Anchorage Area: Anchorage closed',
    42: 'Anchorage Area: Anchoring prohibited',
    43: 'Anchorage Area: Deep draft anchorage',
    44: 'Anchorage Area: Shallow draft anchorage',
    45: 'Anchorage Area: Vessel transfer operations',
    46: 'Reserved',
    47: 'Reserved',
    48: 'Reserved',
    49: 'Reserved',
    50: 'Reserved',
    51: 'Reserved',
    52: 'Reserved',
    53: 'Reserved',
    54: 'Reserved',
    55: 'Reserved',
    56: 'Security Alert - Level 1',
    57: 'Security Alert - Level 2',
    58: 'Security Alert - Level 3',
    59: 'Reserved',
    60: 'Reserved',
    61: 'Reserved',
    62: 'Reserved',
    63: 'Reserved',
    64: 'Distress Area: Vessel disabled and adrift',
    65: 'Distress Area: Vessel sinking',
    66: 'Distress Area: Vessel abandoning ship',
    67: 'Distress Area: Vessel requests medical assistance',
    68: 'Distress Area: Vessel flooding',
    69: 'Distress Area: Vessel fire/explosion',
    70: 'Distress Area: Vessel grounding',
    71: 'Distress Area: Vessel collision',
    72: 'Distress Area: Vessel listing/capsizing',
    73: 'Distress Area: Vessel under assault',
    74: 'Distress Area: Person overboard',
    75: 'Distress Area: SAR area',
    76: 'Distress Area: Pollution response area',
    77: 'Reserved',
    78: 'Reserved',
    79: 'Reserved',
    80: 'Instruction: Contact VTS at this point/juncture',
    81: 'Instruction: Contact Port Administration at this point/juncture',
    82: 'Instruction: Do not proceed beyond this point/juncture',
    83: 'Instruction: Await instructions prior to proceeding beyond this point/juncture',
    84: 'Proceed to this location - await instructions',
    85: 'Clearance granted - proceed to berth',
    86: 'Reserved',
    87: 'Reserved',
    88: 'Information: Pilot boarding position',
    89: 'Information: Icebreaker waiting area',
    90: 'Information: Places of refuge',
    91: 'Information: Position of icebreakers',
    92: 'Information: Location of response units',
    93: 'Reserved',
    94: 'Reserved',
    95: 'Reserved',
    96: 'Chart Feature: Sunken vessel',
    97: 'Chart Feature: Submerged object',
    98: 'Chart Feature: Semi-submerged object',
    99: 'Chart Feature: Shoal area',
    100: 'Chart Feature: Shoal area due North',
    101: 'Chart Feature: Shoal area due East',
    102: 'Chart Feature: Shoal area due South',
    103: 'Chart Feature: Shoal area due West',
    104: 'Chart Feature: Channel obstruction',
    105: 'Chart Feature: Reduced vertical clearance',
    106: 'Chart Feature: Bridge closed',
    107: 'Chart Feature: Bridge partially open',
    108: 'Chart Feature: Bridge fully open',
    109: 'Reserved',
    110: 'Reserved',
    111: 'Reserved',
    112: 'Report from ship: Icing info',
    113: 'Reserved', # USCG called this report from ship: intended route
    114: 'Report from ship: Miscellaneous information - define in free text field',
    115: 'Reserved',
    116: 'Reserved',
    117: 'Reserved',
    118: 'Reserved',
    119: 'Reserved',
    120: 'Route: Recommended route',
    121: 'Route: Alternate route',
    122: 'Route: Recommended route through ice',
    123: 'Reserved',
    124: 'Reserved',
    125: 'Other - Define in free text field',
    126: 'Cancellation - cancel area as identified by Message Linka',
    127: 'Undefined (default)',
}
''' by name or number.

 cau == caution area
 res == restricted
 anc == anchorage
 env == environmental caution
 sec == security
 des == distress
 inst == instructional
 info == informational
 chart == chart features'''

shape_types = {
    0: 'circle_or_point',
    1: 'rectangle',
    2: 'sector',
    3: 'polyline',
    4: 'polygon',
    5: 'free_text',
    6: 'reserved',
    7: 'reserved',
    'circle_or_point':0 ,
    'rectangle': 1,
    'sector': 2,
    'polyline': 3,
    'polygon': 4,
    'free_text': 5,
    }

def _make_short_notice():
    d = {}
    for k,v in notice_type.iteritems():
        if isinstance (k,str):
            d[v] = k
    return d

short_notice = _make_short_notice()


def lon_to_utm_zone(lon):
    return int(( lon + 180 ) / 6) + 1

#def ll_to_delta_m (lon1, lat1, lon2, lat2):
    #'calculate dx and dy in meters between two points'
    #zone = lon_to_utm_zone( (lon1 + lon2 ) / 2.) # Just don't cross the dateline!
    #params = {'proj':'utm', 'zone':zone}
    #proj = Proj(params)

    #utm1 = proj(lon1,lat1)
    #utm2 = proj(lon2,lat2)

    #return utm2[0]-utm1[0],utm2[1]-utm1[1]

#def dist(p1,p2):
    #return math.sqrt( (p1[0]-p2[0])*(p1[0]-p2[0]) + (p1[1]-p2[1])*(p1[1]-p2[1]) )

#def deltas_to_angle_dist(deltas_m):
    #r = []
    #for i in range(1,len(deltas_m)):
        #p1 = deltas_m[i-1]
        #p2 = deltas_m[i]
        #dist_m = dist(p1, p2)
        ##print ('angle_from:',p2[1]-p1[1], dist_m)
        #angle = math.acos( (p2[1]-p1[1]) / dist_m) # cos alpha = dy / dist_m
        #if p2[0]<p1[0]:
            ##print ('switching_sense:',angle,2*math.pi-angle)
            #angle = 2*math.pi - angle
        #r.append((math.degrees(angle),dist_m))
    #return r

def ll_to_polyline(ll_points):
    # Skips the first point as that is returned as an x,y.  ll==lonlat
    ll = ll_points
    assert(len(ll)>=2)
    #deltas_m = [(0,0)]
    offsets = []
    for i in range(1,len(ll)):
        offsets.append(geodesic.inverse(ll[i-1][0],ll[i-1][1], ll[i][0],ll[i][1]))
        #dx_m,dy_m = ll_to_delta_m(ll[i-1][0],ll[i-1][1], ll[i][0],ll[i][1])
        #deltas_m.append((dx_m,dy_m))
    #offsets = deltas_to_angle_dist(deltas_m)
    #print ('ll_points:',ll_points)
    #print ('deltas_m:',deltas_m)
    #print ('angles_and_offsets:',offsets)
    return offsets

def polyline_to_ll(start, angles_and_offsets):
    # start lon,lat plus a list of (angle,offset) from that point
    # 0 is true north and runs clockwise
    points = angles_and_offsets
    cur = start[:]
    pts = [cur]
    
    #lon,lat = start
    #zone = lon_to_utm_zone(lon)
    #params = {'proj':'utm','zone':zone}
    #proj = Proj(params)

    #p1 = proj(lon,lat)

    #pts = [(0,0)]
    #cur = (0,0)
    #print ('points:',points)
    for pt in points:
        
        #alpha = math.radians(pt[0]) # Angle
        d = pt[1] # Offset
        #print ('cur:',cur)
        cur = geodesic.direct(cur[0],cur[1],pt[0],d)
        #print ('pt:',pt,'cur:',cur)
        #dx,dy = d * math.sin(alpha), d * math.cos(alpha)
        #cur = vec_add(cur,(dx,dy))
        #print ('pt:',proj(*cur,inverse=True))
        pts.append(cur)

    #print (pts)
    #pts = [vec_add(p1,pt) for pt in pts]
    #pts = [proj(*pt,inverse=True) for pt in pts]
    
    return pts

def frange(start, stop=None, step=None):
    'range but with float steps'
    if stop is None:
        stop = float(start)
        start = 0.0
    if step is None:
        step = 1.0
    cur = float(start)
    while cur < stop:
        yield cur
        cur += step


def vec_add(a,b):
    return map(operator.add,a,b)

def vec_rot(a, theta):
    'counter clockwise rotation by theta radians'
    x,y = a
    x1 = x * math.cos(theta) - y * math.sin(theta)
    y1 = x * math.sin(theta) + y * math.cos(theta)
    return x1,y1

# math.radians
#def deg2rad(degrees):
#    return (degrees / 180.) * math.pi

# math.degrees
#def rad2deg(radians):
#    return (radians / math.pi) * 180.

def geom2kml(geom_dict):
    '''Convert a geointerface geometry to KML
    
    @param geom_dict: Dictionary containing 'geometry' as defined by the geo interface / geojson / shapely
    '''
    geom_type = geom_dict['geometry']['type']
    geom_coords = geom_dict['geometry']['coordinates']

    if geom_type == 'Point':
        return '<Point><coordinates>{lon},{lat},0</coordinates></Point>'.format(lon = geom_coords[0], lat = geom_coords[1])
    elif geom_type == 'Polygon':
        o = ['<Polygon><outerBoundaryIs><LinearRing><coordinates>']
        for pt in geom_coords:
            o.append('\t%f,%f,0' % (pt[0],pt[1]))
        o.append('</coordinates></LinearRing></outerBoundaryIs></Polygon>')
        return '\n'.join(o)

    elif geom_type == 'LineString':
        o = ['<LineString><coordinates>']
        for pt in geom_coords:
            o.append('\t%f,%f,0' % (pt[0],pt[1]))
        o.append('</coordinates></LineString>')
        return '\n'.join(o)

    raise ValueError('Not a recognized __geo_interface__ type: %s' % (geom_type))


# FIX: should this subclass BaseException?
class AisException(Exception):
    pass

class AisPackingException(AisException):
    def __init__(self, msg):#fieldname, value):
        self.msg = msg
    def __repr__(self):
        return msg

class AisUnpackingException(AisException):
    def __init__(self, msg):
        self.msg = msg
        #self.fieldname = fieldname
        #self.value = value
    def __repr__(self):
        return msg#"Validation on %s failed (value %s) while unpacking" % (self.fieldname, self.value)


def nmea_checksum_hex(sentence):
    '8-bit XOR of everything between the [!$] and the *'
    nmea = map(ord, sentence.split('*')[0][1:])
    checksum = reduce(xor, nmea)
    checksum_str = hex(checksum).split('x')[1].upper()
    if len(checksum_str) == 1:
        checksum_str = '0' + checksum_str
    assert len(checksum_str) == 2
    return checksum_str

class AIVDM (object):
    '''AIS VDM Object for AIS top level messages 1 through 64.

    Class attribute payload_bits must be set by the child class.
    '''
    def __init__(self, message_id = None, repeat_indicator = None, source_mmsi = None):
        self.message_id = message_id
        self.repeat_indicator = repeat_indicator
        self.source_mmsi = source_mmsi

    def get_bits(self):
        '''Child classes must implement this.  Return a BitVector
        representation.  Child classes do NOT include the Message ID, repeat indicator, or source mmsi'''
        raise NotImplementedError()

    def get_bits_header(self, message_id = None, repeat_indicator = None, source_mmsi = None):
        if message_id       is None: message_id       = self.message_id
        if repeat_indicator is None: repeat_indicator = self.repeat_indicator
        if source_mmsi      is None: source_mmsi      = self.source_mmsi

        if message_id is None or message_id<1 or message_id>63:
            raise AisPackingException('message_id must be valid',message_id)
        if repeat_indicator is None or repeat_indicator<0 or repeat_indicator>3:
            raise AisPackingException('repeat_indicator must be valid: [%s]' % (repeat_indicator,))

        #print ('\naivdm_header:',message_id,repeat_indicator,source_mmsi)
        bvList = []
	bvList.append(binary.setBitVectorSize(BitVector(intVal=message_id),6))
        bvList.append(binary.setBitVectorSize(BitVector(intVal=repeat_indicator),2))
        bvList.append(binary.setBitVectorSize(BitVector(intVal=source_mmsi),30))
        bv = binary.joinBV(bvList)
        if len(bv) != 38:
            raise AisPackingExpeption('invalid  header size',len(bv))
        return bv

# See __geo_interface__
#    def get_json(self):
#        'Child classes must implement this.  Return a json object'
#        raise NotImplementedError()

    def get_aivdm(self, sequence_num = None, channel = 'A', normal_form=False, source_mmsi=None, repeat_indicator=None, byte_align=False):
        '''return the nmea string as if it had been received.  Assumes that payload_bits has already been set
        @param sequence_num: Which channel of AIVDM on the local serial line (in 0..9)
        @param channel: VHF radio channel ("A" or "B")
        @param normal_form:  Set to true to always return aone line NMEA message.  False allows multi-sentence messages
        @param byte_align:  The spec says messages must be byte aligned.
        @return: AIVDM sentences
        @rtype: list (even for normal_form for consistency)
        '''
        if sequence_num is not None and (sequence_num <= 0 or sequence_num >= 9):
            raise AisPackingException('sequence_num %d' % sequence_num)
        if channel not in ('A','B'):
            raise AisPackingException('channel',channel)

        if repeat_indicator is None:
            try:
                repeat_indicator = self.repeat_indicator
            except:
                repeat_indicator = 0

        if source_mmsi is None:
            try:
                source_mmsi = self.source_mmsi
            except:
                raise AisPackingException('source_mmsi',source_mmsi)

        header = self.get_bits_header(repeat_indicator=repeat_indicator,source_mmsi=source_mmsi)

        #payload, pad = binary.bitvectoais6(header + self.get_bits())
        bits = header + self.get_bits()
        if byte_align:
            bits_over = len(bits) % 8
            bits_needed = 0 if 0==bits_over else 8 - len(bits) % 8 
            if bits_over != 0:
                sys.stderr.write('WARNING: non-byte aligned message %d - over: %d  need: %d\n' % (len(bits), bits_over,bits_needed ))
                bits = bits + BitVector(size=bits_needed)
                assert(len(bits) % 8 ==0)
            else:
                sys.stderr.write('byte-aligned okay\n')

        payload, pad = binary.bitvectoais6(bits)

        
        if normal_form:
            # Build one big NMEA string no matter what

            if sequence_num is None:
                sequence_num = ''

            sentence = '!AIVDM,{tot_sentences},{sentence_num},{sequence_num},{channel},{payload},{pad}'.format(
                tot_sentences=1, sentence_num=1,
                sequence_num=sequence_num, channel=channel,
                payload=payload, pad=pad
                )
            return [sentence + '*' + nmea_checksum_hex(sentence),]

        max_payload_char = 43

        sentences = []
        tot_sentences = 1 + len(payload) / max_payload_char
        sentence_num = 0

        if sequence_num is None:
            if tot_sentences == 1:
                sequence_num = ''  # Make empty
            else:
                global next_sequence
                sequence_num = next_sequence
                next_sequence += 1
                if next_sequence > 9: next_sequence = 1
                
        for i in range(tot_sentences-1):
            sentence_num = i+1
            payload_part = payload[i*max_payload_char:(i+1)*max_payload_char]
            sentence = '!AIVDM,{tot_sentences},{sentence_num},{sequence_num},{channel},{payload},{pad}'.format(
                tot_sentences=tot_sentences, sentence_num=sentence_num,
                sequence_num=sequence_num, channel=channel,
                payload=payload_part, pad=0
                )
            sentences.append(sentence + '*' + nmea_checksum_hex(sentence))

        sentence_num += 1
        payload_part = payload[(sentence_num-1)*max_payload_char:]
        sentence = '!AIVDM,{tot_sentences},{sentence_num},{sequence_num},{channel},{payload},{pad}'.format(
                tot_sentences=tot_sentences, sentence_num=sentence_num,
                sequence_num=sequence_num, channel=channel,
                payload=payload_part, pad=pad # The last part gets the pad
                )
        sentences.append(sentence + '*' + nmea_checksum_hex(sentence))

        return sentences

    def kml(self,with_style=False,full=False,with_time=False, with_extended_data=False):
        '''return kml str for google earth
        @param with_style: if style is True, it will use the standard style.  Set to a name for a custom style
        @param with_time: enable timestamps in Google Earth
        '''
        o = []
        if full:
            o.append(kml_head)
            o.append(file('areanotice_styles.kml').read())
        html = self.html()
        for area in self.areas:
            geo_i = area.__geo_interface__
            if 'geometry' not in geo_i:
                #print ('Skipping area:',str(area))
                continue
            kml_shape = geom2kml(geo_i)

            o.append('<Placemark>')
            try:
                o.append('<name>%s</name>' % (self.name))
            except:
                o.append('<name>%s</name>' % (short_notice[self.area_type].replace('_',' '),))
            if with_style:
                if isinstance(with_style,str):
                    o.append('<styleUrl>%s</styleUrl>'% (with_style,))
                o.append('<styleUrl>#AreaNotice_%d</styleUrl>' % self.area_type)

            if with_extended_data:
                o.append('<ExtendedData>')
                #print ('self.__dict__:',self.__dict__)

                for key in ( 'message_id', 'source_mmsi', 'dac', 'fi', 'link_id', 'when', 'duration', 'area_type', ):
                    o.append('\t<Data name="{key}"><value>{value}</value></Data>'.format(key=key,value=self.__dict__[key]))

                o.append('</ExtendedData>\n')

            o.append('<description>')
            o.append('<i>AreaNotice - %s</i>' % (notice_type[self.area_type],) )
            o.append(html)
            o.append('</description>')

            o.append(kml_shape)
            if with_time:
                start = datetime.datetime.strftime(self.when,iso8601_timeformat)
                end = datetime.datetime.strftime(self.when + datetime.timedelta(minutes=self.duration),iso8601_timeformat)
                o.append('''<TimeSpan><begin>%s</begin><end>%s</end></TimeSpan>''' % (start,end))

            o.append('</Placemark>\n')

        if full:
            o.append(kml_tail)

        return '\n'.join(o)


class BBM (AIVDM):
    ''' Binary Broadcast Message - MessageID 8.  Generically support messages of this type
    BBM defined in 80_330e_PAS - IEC/PAS 61162-100 Ed.1

    Maritime navigation and radiocommunication equipment and systems -
    Digital interfaces - Part 100: Singlto IEC 61162-1 for the UAIS

    NMEA BBM can be 8, 19, or 21.  It can also handle the text message 14.
    '''
    max_payload_char = 41
    'Maximum length of characters that can go inside the BBM payload'

    def __init__(self,message_id = 8):
        assert message_id in (8, 19, 21)
        self.message_id = message_id

    def get_bbm(self, talker='EC', sequence_num = None, channel = 0):
        '''channel is:
        0 - no pref
        1 - A
        2 - B
        3 - both
        '''        
        if not isinstance(talker,str) or len(talker) != 2:
            AisPackingException('talker',talker)
        if sequence_num is not None and (sequence_num <= 0 or sequence_num >= 9):
            raise AisPackingException('sequence_num',sequence_num)
        if channel not in (0,1,2,3): #('A','B'):
            raise AisPackingException('channel',channel)

        if sequence_num is None:
            sequence_num = 3
       
        payload, pad = binary.bitvectoais6(self.get_bits())
        
        sentences = []
        tot_sentences = 1 + len(payload) / self.max_payload_char
        sentence_num = 0
        for i in range(tot_sentences-1):
            sentence_num = i+1
            payload_part = payload[i*self.max_payload_char:(i+1)*self.max_payload_char]
            sentence = '!{talker}BBM,{tot_sentences},{sentence_num},{sequence_num},{channel},{msg_type},{payload},{pad}'.format(
                talker=talker,
                tot_sentences=tot_sentences, sentence_num=sentence_num,
                sequence_num=sequence_num, channel=channel,
                msg_type=self.message_id,
                payload=payload_part, pad=0
                )
            sentences.append(sentence + '*' + nmea_checksum_hex(sentence))

        sentence_num += 1
        payload_part = payload[(sentence_num-1)*self.max_payload_char:]
        sentence = '!{talker}BBM,{tot_sentences},{sentence_num},{sequence_num},{channel},{msg_type},{payload},{pad}'.format(
                talker=talker,
                tot_sentences=tot_sentences, sentence_num=sentence_num,
                sequence_num=sequence_num, channel=channel,
                msg_type=self.message_id,
                payload=payload_part, pad=pad # The last part gets the pad
                )
        sentences.append(sentence + '*' + nmea_checksum_hex(sentence))

        return sentences

class AreaNoticeSubArea(object):
    def __str__(self):
        return self.__unicode__()

# FIX: Warning... there may be an issue with the precision field
class AreaNoticeCirclePt(AreaNoticeSubArea):
    area_shape = 0
    def __init__(self, lon=None, lat=None, radius=0, precision=4, bits=None):
        '''@param radius: 0 is a point, otherwise less than or equal to 409500m.  Scale factor is automatic.  Units are m
        @param bits: string of 1's and 0's or a BitVector
        @param precision: unless tracking of significant digits to show on a display
        '''
        if lon is not None:
            assert lon >= -180. and lon <= 180.
            self.lon = lon
            assert lat >= -90. and lat <= 90.
            self.lat = lat

            assert precision >= 0 and precision <= 4
            self.precision = precision

            assert radius >= 0 and radius < 409500
            self.radius = radius

            if radius / 100. >= 4095: self.scale_factor_raw = 3
            elif radius / 10. > 4095: self.scale_factor_raw = 2
            elif radius > 4095:       self.scale_factor_raw = 1
            else:                     self.scale_factor_raw = 0

            self.scale_factor = (1,10,100,1000)[self.scale_factor_raw]
            self.radius_scaled = radius / self.scale_factor
            return

        elif bits is not None:
            self.decode_bits(bits)
            return

        return # Return an empty object


    def decode_bits(self, bits):
        if len(bits) != SUB_AREA_SIZE: raise AisUnpackingException('bit length',len(bits))
        if isinstance(bits,str):
            bits = BitVector(bitstring = bits)
        elif isinstance(bits, list) or isinstance(bits,tuple):
            bits = BitVector ( bitlist = bits)

        self.area_shape = int( bits[:3] )
        self.scale_factor_raw = int( bits[3:5] )
        self.scale_factor = (1,10,100,1000)[self.scale_factor_raw]
        self.lon = binary.signedIntFromBV( bits[ 5:30] ) / 60000.
        self.lat = binary.signedIntFromBV( bits[30:54] ) / 60000.
        self.precision = int( bits[54:57] )
        
        self.radius_scaled = int( bits[57:69] )

        self.radius = self.radius_scaled * self.scale_factor

        spare = int( bits[69:] )
        assert (18 == SUB_AREA_SIZE - 69)
        #assert 0 == spare
        

    def get_bits(self):
        'Build a BitVector for this area'
        bvList = []
        bvList.append( binary.setBitVectorSize( BitVector(intVal=self.area_shape ), 3) )
        bvList.append( binary.setBitVectorSize( BitVector(intVal=self.scale_factor_raw), 2 ) )
        bvList.append( binary.bvFromSignedInt( int(self.lon*60000), 25 ) )
        bvList.append( binary.bvFromSignedInt( int(self.lat*60000), 24 ) )
        bvList.append( binary.setBitVectorSize( BitVector(intVal=self.precision), 3 ) )
        bvList.append( binary.setBitVectorSize( BitVector(intVal=self.radius_scaled), 12 ) )
        bvList.append( binary.setBitVectorSize( BitVector(intVal=0), 18 ) ) # spare
        bv = binary.joinBV(bvList)
        if SUB_AREA_SIZE != len(bv):
            #print ('len:',[len(b) for b in bvList])
            raise AisPackingException('area not '+str(SUB_AREA_SIZE)+' bits',len(bv))
        #print 'subarea_bv:',bv
        return bv

    def __unicode__(self):
        if self.radius == 0.:
            return 'AreaNoticeCirclePt: Point at (%.4f,%.4f)' % (self.lon,self.lat)
        return 'AreaNoticeCirclePt: Circle centered at (%.4f,%.4f) - radius %dm' % (self.lon,self.lat,self.radius)

#    def __str__(self):
#        return self.__unicode__()

    def geom(self):
        #if 'geom_geographic' not in self.__dict__:
        # If I do this, will need to make sure that I invalidate the cache
        if self.radius <= 0.01:
            return shapely.geometry.Point(self.lon,self.lat)

        # Circle
        zone = lon_to_utm_zone(self.lon)
        params = {'proj':'utm','zone':zone}
        proj = Proj(params)

        utm_center = proj(self.lon,self.lat)
        pt = shapely.geometry.Point(utm_center)
        circle_utm = pt.buffer(self.radius) #9260)

        circle = shapely.geometry.Polygon( [ proj(pt[0],pt[1],inverse=True) for pt in circle_utm.boundary.coords])

        return circle

    @property
    def __geo_interface__(self):
        'Provide a Geo Interface for GeoJSON serialization'
        # Would be better if there was a GeoJSON Circle type!

# NOT in the shape... crap... this is wrong
#        area_shape_desc = 'unknown'
#        if self.area_shape in notice_type:
#            area_shape_desc = notice_type[self.area_shape]

        if self.radius == 0.:
            return {'area_shape': self.area_shape,
                    #'area_shape_desc': area_shape_desc,
                    'area_shape_name': 'point',
                    'geometry': {'type': 'Point', 'coordinates': [self.lon, self.lat] }
                    }

        # self.radius > 0 ... circle
        r = {
            'area_shape': self.area_shape, 
            #'area_shape_desc': area_shape_desc,
            'area_shape_name': 'circle',
            'center_ll': [self.lon, self.lat],
            'radius_m':self.radius,
            'geometry': {'type': 'Polygon', 'coordinates': tuple(self.geom().boundary.coords) },
            #'geometry': {'type': 'Polygon', 'coordinates': [pt for pt in self.geom().boundary.coords]},
            # Leaving out scale_factor
            }
        return r

class AreaNoticeRectangle(AreaNoticeSubArea):
    area_shape = 1
    def __init__(self, lon=None, lat=None, east_dim=0, north_dim=0, orientation_deg=0, precision=4, bits=None):
        '''
        Rotatable rectangle
        @param lon: WGS84 longitude
        @param lat: WGS84 latitude
        @param east_dim: width in meters (this gets confusing for larger angles).  0 is a north-south line
        @param north_dim: height in meters (this gets confusing for larger angles). 0 is an east-west line
        @param orientation_deg: degrees CW

        @todo: great get/set for dimensions and allow for setting scale factor.
        @todo: or just over rule the attribute get and sets
        @todo: allow user to force the scale factor
        @todo: Should this be raising a ValueError 
        '''
        if lon is not None:
            assert lon >= -180. and lon <= 180.
            self.lon = lon
            assert lat >= -90. and lat <= 90.
            self.lat = lat

            assert precision >= 0 and precision <= 4
            self.precision = precision

            assert 0 <=  east_dim and  east_dim <= 255000 # 25.5 km
            assert 0 <= north_dim and north_dim <= 255000

            assert 0 <= orientation_deg and orientation_deg < 360

            if east_dim / 100. >= 255 or north_dim / 100. >= 255:  self.scale_factor_raw = 3
            elif east_dim / 10. >= 255 or north_dim / 100. >= 255: self.scale_factor_raw = 2
            elif east_dim >= 255 or north_dim >= 255:              self.scale_factor_raw = 1
            else:                                                  self.scale_factor_raw = 0
            self.scale_factor = (1,10,100,1000)[self.scale_factor_raw]

            self.e_dim = east_dim
            self.n_dim = north_dim
            self.e_dim_scaled = east_dim / self.scale_factor
            self.n_dim_scaled = north_dim / self.scale_factor

            self.orientation_deg = orientation_deg

        elif bits is not None:
            self.decode_bits(bits)

    def decode_bits(self,bits):
        if len(bits) != SUB_AREA_SIZE: raise AisUnpackingException('bit length',len(bits))
        #print 'decoded:',bits
        if isinstance(bits,str):
            bits = BitVector(bitstring = bits)
        elif isinstance(bits, list) or isinstance(bits,tuple):
            bits = BitVector ( bitlist = bits)

        self.area_shape = int( bits[:3] )
        self.scale_factor = int( bits[3:5] )
        self.lon = binary.signedIntFromBV( bits[ 5:30] ) / 60000.
        self.lat = binary.signedIntFromBV( bits[30:54] ) / 60000.
        self.precision = int( bits[54:57] )

        self.e_dim_scaled = int ( bits[57:65] ) # was 60:68
        self.n_dim_scaled = int ( bits[65:73] ) # was 68:76

        self.e_dim = self.e_dim_scaled * (1,10,100,1000)[self.scale_factor]
        self.n_dim = self.n_dim_scaled * (1,10,100,1000)[self.scale_factor]

        self.orientation_deg = int ( bits[73:82] ) # was 76:85

        self.spare = int ( bits[82:] )

    def get_bits(self):
        bvList = []
        bvList.append( binary.setBitVectorSize( BitVector(intVal=self.area_shape), 3 ) )
        #xsscale_factor = {1:0,10:1,100:2,1000:3}[self.scale_factor]
        bvList.append( binary.setBitVectorSize( BitVector(intVal=self.scale_factor_raw), 2 ) )
        bvList.append( binary.bvFromSignedInt( int(self.lon*60000), 25 ) )
        bvList.append( binary.bvFromSignedInt( int(self.lat*60000), 24 ) )
        bvList.append( binary.setBitVectorSize( BitVector(intVal=self.precision), 3 ) )
        #print 'dim:',self.e_dim_scaled,self.n_dim_scaled, self.scale_factor
        bvList.append( binary.setBitVectorSize( BitVector(intVal=self.e_dim_scaled), 8 ) )
        bvList.append( binary.setBitVectorSize( BitVector(intVal=self.n_dim_scaled), 8 ) )
        bvList.append( binary.setBitVectorSize( BitVector(intVal=self.orientation_deg), 9 ) )
        bvList.append( binary.setBitVectorSize( BitVector(intVal=0), 5 ) ) # spare
        #print '\nlen:',[len(b) for b in bvList]
        bv = binary.joinBV(bvList)
        assert SUB_AREA_SIZE==len(bv)
        #print 'rect bits... initial'
        #print 'encoded:',bv
        return bv
    
    def __unicode__(self):
        return 'AreaNoticeRectangle: (%.4f,%.4f) [%d,%d]m rot: %d deg' % (self.lon,self.lat,self.e_dim,self.n_dim,self.orientation_deg)

#    def __str__(self):
#        return self.__unicode__()


    def geom(self):
        'return shapely geometry object'
        zone = lon_to_utm_zone(self.lon)
        params = {'proj':'utm', 'zone':zone}
        proj = Proj(params)

        p1 = proj(self.lon,self.lat)

        pts = [(0,0), (self.e_dim,0), (self.e_dim,self.n_dim), (0,self.n_dim)]

        #print 'before:',pts
        rot = math.radians(-self.orientation_deg)
        pts = [vec_rot(pt,rot) for pt in pts]

        pts = [vec_add(p1,pt) for pt in pts]
        pts = [proj(*pt,inverse=True) for pt in pts]

        return shapely.geometry.Polygon(pts)

    @property
    def __geo_interface__(self):
        '''Provide a Geo Interface for GeoJSON serialization
        @todo: Write the code to build the polygon with rotation'''
        r = {
            'area_shape': self.area_shape, 'area_shape_name': 'rectangle',
            'orientation': self.orientation_deg,
            'e_dim': self.e_dim, 'n_dim': self.n_dim,
            'geometry': {'type':'Polygon', 'coordinates':  tuple(self.geom().boundary.coords) },
            }

        return r

  
class AreaNoticeSector(AreaNoticeSubArea):
    area_shape = 2
    def __init__(self, lon=None, lat=None, radius=0, left_bound_deg=0, right_bound_deg=0, precision=4, bits=None):
        '''
        A pie slice

        @param lon: WGS84 longitude
        @param lat: WGS84 latitude
        @param radius: width in meters
        @param left_bound_deg: Orientation of the left boundary.  CW from True North
        @param right_bound_deg: Orientation of the right boundary.  CW from True North
        @param precision: useless suggestion for the display.  Leave 4

        @todo: great get/set for dimensions and allow for setting scale factor.
        @todo: or just over rule the attribute get and sets
        @todo: allow user to force the scale factor
        @todo: Should this be raising a ValueError 
        '''
        if lon is not None:
            assert lon >= -180. and lon <= 180.
            self.lon = lon
            assert lat >= -90. and lat <= 90.
            self.lat = lat

            assert precision >= 0 and precision <= 4
            self.precision = precision

            assert 0 <=  radius and  radius <= 25500

            assert 0 <=  left_bound_deg and  left_bound_deg < 360
            assert 0 <= right_bound_deg and right_bound_deg < 360

            assert left_bound_deg <= right_bound_deg

            if radius / 100. >= 4095: self.scale_factor_raw = 3
            elif radius / 10. > 4095: self.scale_factor_raw = 2
            elif radius > 4095:       self.scale_factor_raw = 1
            else:                     self.scale_factor_raw = 0
            self.scale_factor = (1,10,100,1000)[self.scale_factor_raw]
            self.radius = radius
            self.radius_scaled = int( radius / self.scale_factor)

            self.left_bound_deg  = left_bound_deg
            self.right_bound_deg = right_bound_deg

        elif bits is not None:
            self.decode_bits(bits)

    def decode_bits(self,bits):
        if len(bits) != SUB_AREA_SIZE: raise AisUnpackingException('bit length',len(bits))
        if isinstance(bits,str):
            bits = BitVector(bitstring = bits)
        elif isinstance(bits, list) or isinstance(bits,tuple):
            bits = BitVector ( bitlist = bits)

        self.area_shape = int( bits[:3] )
        self.scale_factor = int( bits[3:5] )
        self.lon = binary.signedIntFromBV( bits[ 5:30] ) / 60000.
        self.lat = binary.signedIntFromBV( bits[30:54] ) / 60000.
        self.precision = int( bits[54:57] )

        self.radius_scaled = int ( bits[57:69] ) # was 60:72

        self.radius = self.radius_scaled * (1,10,100,1000)[self.scale_factor]

        self.left_bound_deg = int ( bits[68:78] ) # was 72:81
        self.right_bound_deg = int ( bits[78:87] ) # was 81:90

    def get_bits(self):
        
        'Build a BitVector for this area'
        bvList = []
        bvList.append( binary.setBitVectorSize( BitVector(intVal=self.area_shape ), 3) )
        bvList.append( binary.setBitVectorSize( BitVector(intVal=self.scale_factor_raw), 2 ) )
        bvList.append( binary.bvFromSignedInt( int(self.lon*60000), 25 ) )
        bvList.append( binary.bvFromSignedInt( int(self.lat*60000), 24 ) )
        bvList.append( binary.setBitVectorSize( BitVector(intVal=self.precision), 3 ) )

        bvList.append( binary.setBitVectorSize( BitVector(intVal=self.radius_scaled), 12 ) )
        bvList.append( binary.setBitVectorSize( BitVector(intVal=self.left_bound_deg), 9 ) )
        bvList.append( binary.setBitVectorSize( BitVector(intVal=self.right_bound_deg), 9 ) )

        #print 'len:',[len(bv) for bv in bvList]
        bv = binary.joinBV(bvList)
        assert SUB_AREA_SIZE==len(bv)
        return bv

    def __unicode__(self):
        return 'AreaNoticeSector: (%.4f,%.4f) %d rot: %d to %d deg' % (self.lon, self.lat, self.radius, 
                                                                       self.left_bound_deg, self.right_bound_deg)
#    def __str__(self):
#        return self.__unicode__()

    def geom(self):
        'return shapely geometry object'
        zone = lon_to_utm_zone(self.lon)
        params = {'proj':'utm', 'zone':zone}
        proj = Proj(params)

        p1 = proj(self.lon,self.lat)

        pts = [ vec_rot( (0,self.radius), math.radians(-angle) ) for angle in frange(self.left_bound_deg, self.right_bound_deg+0.01, 0.5) ]
        pts = [(0,0),] + pts + [(0,0),]

        pts = [vec_add(p1,pt) for pt in pts] # Move to the right place in the world
        pts = [proj(*pt,inverse=True) for pt in pts] # Project back to geographic
        
        return shapely.geometry.Polygon(pts)

    @property
    def __geo_interface__(self):
        '''Provide a Geo Interface for GeoJSON serialization
        @todo: Write the code to build the polygon with rotation'''
        r = {
            'area_shape': self.area_shape, 'area_shape_name': 'sector',
            'left_bound': self.left_bound_deg,
            'right_bound': self.right_bound_deg,
            'radius': self.radius,
            'geometry': {'type':'Polygon', 'coordinates':  tuple(self.geom().boundary.coords) },
            }

        return r

class AreaNoticePolyline(AreaNoticeSubArea):
    area_shape = 3
    def __init__(self, points=None,
                 lon=None, lat=None,
                 bits=None):
        '''A line or open area.  If an area, this is the area to the
        left of the line.  The line starts at the prior line.  Must set p1
        or provide bits.  You will not be able to get the geometry if you
        do not provide a lon,lat for the starting point

        The lon, lat point comes before the line.  This makes decoding tricky.

        Angles can be specified with a resolution with 0.5 degrees.
        
        @param points: 1 to 4 relative offsets (angle in degrees [0..360] , distance in meters) 
        @param lon: WGS84 longitude of the starting point.  Must match the previous point
        @param lat: WGS84 longitude of the starting point.  Must match the previous point
        @param bits: bits to decode from
        @todo: FIX: make sure that the AreaNotice decode bits passes the lon, lat
        @todo: FIX: Handle sectors that cross 0/360
        '''

        if lon is not None:
            assert lon >= -180. and lon <= 180.
            self.lon = lon
            assert lat >= -90. and lat <= 90.
            self.lat = lat

        # FIX: check the number of points to make sure we have room
        # and generate multiple subareas if need be.

        if points is not None:
            assert len(points)>0 and len(points)<5
            self.points = points

            max_dist = max([pt[1] for pt in points])
            if max_dist / 100. >= 1023: self.scale_factor_raw = 3
            elif max_dist / 10. > 1023: self.scale_factor_raw = 2
            elif max_dist > 1023:       self.scale_factor_raw = 1
            else:                       self.scale_factor_raw = 0
            self.scale_factor = (1,10,100,1000)[self.scale_factor_raw]

        elif bits is not None:
            assert lon is not None
            assert lat is not None
            self.decode_bits(bits, lon, lat)

    def decode_bits(self, bits, lon, lat):
        'lon and lat are the starting point for the point'
        
        if len(bits) != SUB_AREA_SIZE: raise AisUnpackingException('bit length',len(bits))
        if isinstance(bits,str):
            bits = BitVector(bitstring = bits)
        elif isinstance(bits, list) or isinstance(bits,tuple):
            bits = BitVector ( bitlist = bits)

        self.area_shape = int( bits[:3] )
        self.scale_factor = int( bits[3:5] )

        self.points = []
        done = False # used to flag when we should have no more points
        for i in range(4):
            base = 5 + i*20
            angle = int ( bits[base:base+10] )
            #print 'angle:',angle
            if angle == 720:
                #print 'should be no more points'
                done = True
                continue
            else:
                if done and angle != 720:
                    sys.stderr.write('ERROR: bad polyline.  Must have all point with angle 720 (raw) after the first\n')
                    continue
            angle *= 0.5
            dist_scaled = int ( bits[base+10:base+10+10] )
            dist = dist_scaled * (1,10,100,1000)[self.scale_factor]
            self.points.append((angle,dist))
            if 720 == dist_scaled:
                break
        

    def get_bits(self):
        'Build a BitVector for this area'
        bvList = []
        bvList.append( binary.setBitVectorSize( BitVector(intVal=self.area_shape), 3 ) ) # area_shape/type = 0

        bvList.append( binary.setBitVectorSize( BitVector(intVal=self.scale_factor_raw), 2 ) )

        bvList = []
        bvList.append( binary.setBitVectorSize( BitVector(intVal=self.area_shape ), 3) )
        bvList.append( binary.setBitVectorSize( BitVector(intVal=self.scale_factor_raw), 2 ) )

        # Have to emit the starting location as a point
        start_pt_bits = AreaNoticeCirclePt(self.lon,self.lat, radius=0).get_bits()

        # FIX: check range of points
        for pt in self.points:
            # pt is angle, distance
            #print 'scale_factor:',self.scale_factor
            #print 'polyline_seg:',pt,self.scale_factor, pt[1] / self.scale_factor, len(BitVector(intVal=pt[1] / self.scale_factor))
            bvList.append( binary.setBitVectorSize( BitVector(intVal=int(pt[0] * 2)), 10 ) ) # Angle increments of 0.5 degree

            if len(bvList[-1])!=10:
                msg = 'Angle would not fit: %d -> %d bits != 10' % (pt[0],len(bvList[-1]))
                #print ('ERROR:', msg)
                AisPackingException( msg )
                
            #print ('points:',pt[1], self.scale_factor, pt[1] / self.scale_factor)
            # FIX: Is ceil the right thing to do?  e.g. do we always want and area equal to or greater than that requested?
            bvList.append( binary.setBitVectorSize( BitVector(intVal=int(math.ceil(pt[1] / self.scale_factor))), 10 ) )

            if len(bvList[-1])!=10:
                msg = 'Distance would not fit: %d -> %d bits != 10' % (pt[1],len(bvList[-1]))
                AisPackingException( msg )

            #print ( 'len last',len(bvList[-2]),len(bvList[-1]) )

        for i in range(4 - len(self.points)):
            bvList.append( binary.setBitVectorSize( BitVector(intVal=720), 10 ) ) # The marker for no more points
            bvList.append( binary.setBitVectorSize( BitVector(intVal=0), 10 ) ) # No marker specified.  Use 0 fill

        bvList.append( BitVector(size=2) ) # 2 bit 0 values  #intVal=0) )

        bv = binary.joinBV(bvList)
        if len(bv) != SUB_AREA_SIZE:
            print ('Polyline_or_gon_len_error:',[len(b) for b in bvList],'->',len(bv),'is not',SUB_AREA_SIZE)
            raise AisPackingException('area not '+str(SUB_AREA_SIZE)+' bits %d:' % len(bv))

        #raise AisPackingException('wrong size',len(bv))
        return start_pt_bits + bv

    def __unicode__(self):
        return 'AreaNoticePolyline: (%.4f,%.4f) %d points' % ( self.lon, self.lat, len(self.points) )

    def __str__(self):
        return self.__unicode__()

    def get_points(self):
        'Convert to list of (lon,lat) tuples'
        return polyline_to_ll((self.lon,self.lat),self.points)
        # zone = lon_to_utm_zone(self.lon)
        # params = {'proj':'utm','zone':zone}
        # proj = Proj(params)

        # p1 = proj(self.lon,self.lat)

        # pts = [(0,0)]
        # cur = (0,0)
        # for pt in self.points:
        #     alpha = math.radians(pt[0])
        #     d = pt[1]
        #     x,y = d * math.sin(alpha), d * math.cos(alpha)
        #     cur = vec_add(cur,(x,y))
        #     pts.append(cur)

        # pts = [vec_add(p1,pt) for pt in pts]
        # pts = [proj(*pt,inverse=True) for pt in pts]
        # return pts

    def geom(self):
        return shapely.geometry.LineString(self.get_points())

    @property
    def __geo_interface__(self):
        '''Provide a Geo Interface for GeoJSON serialization
        @todo: Write the code to build the polygon with rotation'''
        r = {
            'area_shape':self.area_shape, 'area_shape_name': 'waypoints/polyline',
            'geometry': {'type':'LineString', 'coordinates':  tuple(self.geom().coords) },
            }

        return r


class AreaNoticePolygon(AreaNoticePolyline):
    '''Polyline that wraps back to the beginning.

    For GeoJson, a polygon must have the first and last coordinates
    FIX: handle multi sub area spanning polygons
    '''
    area_shape = 4
    area_name = 'polygon'

    def __unicode__(self):
        return 'AreaNoticePolygon: (%.4f,%.4f) %d points' % ( self.lon, self.lat, len(self.points) )

    def geom(self):
        zone = lon_to_utm_zone(self.lon)
        params = {'proj':'utm','zone':zone}
        proj = Proj(params)

        p1 = proj(self.lon,self.lat)

        pts = [(0,0)]
        cur = (0,0)
        for pt in self.points:
            alpha = math.radians(pt[0])
            d = pt[1]
            x,y = d * math.sin(alpha), d * math.cos(alpha)
            cur = vec_add(cur,(x,y))
            pts.append(cur)
        #print 'pts:',pts

        pts = [vec_add(p1,pt) for pt in pts]
        pts = [proj(*pt,inverse=True) for pt in pts]
        return shapely.geometry.Polygon(pts)

    @property
    def __geo_interface__(self):
        '''Provide a Geo Interface for GeoJSON serialization
        @todo: Write the code to build the polygon with rotation'''
        r = {
            'area_shape':self.area_shape, 'area_shape_name': self.area_name,
            'geometry': {'type':'Polygon', 'coordinates':  tuple(self.geom().boundary.coords) },
            }

        return r

class AreaNoticeFreeText(AreaNoticeSubArea):
    area_shape = 5
    area_name = 'freetext'
    def __init__(self,text=None, bits=None):
        'text must be 14 characters or less'
        if text is not None:
            text = text.upper()
            #if len(text) > 14:
            #   sys.stderr.write('text too long')
            assert len(text) <= 14
            for c in text:
                assert c in aisstring.characterDict
            self.text = text
        elif bits is not None:
            self.decode_bits(bits)

           
    def decode_bits(self, bits):
        'Removes the "@" padding'
        if len(bits) != SUB_AREA_SIZE: raise AisUnpackingException('bit length',len(bits))
        if isinstance(bits,str):
            bits = BitVector(bitstring = bits)
        elif isinstance(bits, list) or isinstance(bits,tuple):
            bits = BitVector ( bitlist = bits)

        area_shape = int( bits[:3] )
        assert self.area_shape == area_shape
        self.text = aisstring.decode(bits[3:]).rstrip('@')

    def get_bits(self):
        'Build a BitVector for this area'
        bvList = []
        bvList.append( binary.setBitVectorSize( BitVector(intVal=self.area_shape), 3 ))
        text = self.text.ljust(14,'@')
        #sys.stderr.write('FIX: get_bits @ "%s" -> "%s"\n' % (self.text,text))
        bvList.append(aisstring.encode(text))
        # No spare

        bv = binary.joinBV(bvList)
        if SUB_AREA_SIZE != len(bv):
            #print ('len_freetext:',[len(b) for b in bvList])
            AisPackingException('text subarea not '+str(SUB_AREA_SIZE)+' bits: %d' % len(bv))
        #if SUB_AREA_SIZE != len(bv):
        #    sys.exit('REALLY BAD FREE TEXT ERROR: %d != %d' % (SUB_AREA_SIZE,len(bv)) )
        assert SUB_AREA_SIZE==len(bv)
        return bv

    def __unicode__(self):
        return 'AreaNoticeFreeText: "%s"' % (self.text,)

#    def __str__(self):
#        return self.__unicode__()

    def geom(self):
        # FIX: should this somehow have a position?
        return None

    @property
    def __geo_interface__(self):
        'Provide a Geo Interface for GeoJSON serialization'
        # FIX: should this return geometry?  Probably not as this text gets built into the message text for other geom
        return {'area_shape': self.area_shape, 
                'area_shape_name': self.area_name,
                'text': self.text,
                # No geometry... 'geometry': {'type': 'Point', 'coordinates': [self.lon, self.lat] }
                }

class AreaNotice(BBM):
    #dac = 1
    #fi = 22
    def __init__(self,area_type=None, when=None, duration=None, link_id=0, nmea_strings=None, source_mmsi=None):
        '''
        @param area_type: 0..127 based on table 11.10
        @param when: when the notice starts
        @type when: datetime (UTC)
        @param duration: minutes for the notice to be in effect
        @param nmea_strings: Pass 1 or more nmea strings as a list
        '''
        self.areas = []

        if nmea_strings != None:
            self.decode_nmea(nmea_strings)
            return

        elif area_type is not None and when is not None and duration is not None:
            # We are creating a new message
            assert area_type >= 0 and area_type <= 127
            self.area_type = area_type
            assert isinstance(when,datetime.datetime)
            #self.when = when
            # Be safe with datetime.  We only have 1 minute precision
            self.when = datetime.datetime(year = when.year,
                                          month = when.month,
                                          day = when.day,
                                          hour = when.hour,
                                          minute = when.minute
                                          # No second or smaller
                                          )
            
            assert duration < 2**18 - 1 # Last number reserved for undefined... what does undefined mean?
            self.duration = duration
            self.link_id = link_id

        else:
            # FIX: raise an exception for not enough info
            assert False

        self.dac = 1
        self.fi = 22

        BBM.__init__(self, message_id = 8) # FIX: move to the beginning of this method

        self.source_mmsi = source_mmsi

    def __unicode__(self,verbose=False):
        result = 'AreaNotice: type=%d  start=%s  duration=%d m  link_id=%d  sub-areas: %d' % (
            self.area_type, str(self.when), self.duration, self.link_id, len(self.areas) )
        if not verbose:
            return result
        if verbose:
            results = [result,]
            for item in self.areas:
                results.append('\t'+unicode(item))
        return '\n'.join(results)

    def __str__(self,verbose=False):
        return self.__unicode__(verbose)

    def html(self, efactory=False):
        '''return an embeddable html representation
        @param efactory: return lxml E-factory'''
        l = E.OL()
        text = self.get_merged_text()
        if text is not None:
            l.append(E.LI('FreeText: '+text))
        for area in self.areas:
            l.append(E.LI(str(area)))
        if efactory:
            return
        return lxml.html.tostring(E.DIV(E.P(self.__str__()),l))


    @property
    def __geo_interface__(self):
        'Return dictionary compatible with GeoJSON-AIVD'

        try:
            repeat = self.repeat_indicator
        except:
            repeat = 0
        if repeat is None: repeat = 0

        try:
            mmsi = self.source_mmsi
        except:
            mmsi = 0
        
        r = { 
            'msgtype':self.message_id,
            'repeat': repeat,
            'mmsi': mmsi,
            "bbm": {
                'bbm_type':(self.dac,self.fi), 
                'bbm_name':'area_notice',
                'area_type': self.area_type,
                'area_type_desc': notice_type[self.area_type],
                # This freetext does not handle if there are separate free text blocks for different geometry
                'freetext': self.get_merged_text(),
                'start': self.when.strftime(iso8601_timeformat),
                'stop': (self.when + datetime.timedelta(minutes=self.duration)).strftime(iso8601_timeformat),
                'duration_min': self.duration,
                'areas': [],
                'link_id': self.link_id,
                }
            }

        #print 'areas:',len(self.areas)
        #print 'bbm:',r['bbm']
        for area in self.areas:
            #print 'area_geo:',area.__geo_interface__
            r['bbm']['areas'].append(area.__geo_interface__)

        return r

    def get_merged_text(self):
        'return the complete text for any free text sub areas'
        strings = []
        for a in self.areas:
            if isinstance(a,AreaNoticeFreeText):
                strings.append(a.text)

        # FIX: remove
        # if len(strings)>0:
        #     sys.stderr.write('string_parts:\n')
        #     for s in strings:
        #         sys.stderr.write('   "' + s + '"\n')
            
        if len(strings) == 0: return None
        return ''.join(strings)
        
    def add_subarea(self,area):
        #print 'len_subareas_before:',len(self.areas)
        if not hasattr(self,'areas'):
            self.areas = []
        #print 'len(self.areas):',len(self.areas)
        if len(self.areas) >= 9:
            raise AisPackingException('Can only have 9 sub areas in an Area Notice')
        
        self.areas.append(area)

    def get_bits(self, include_bin_hdr=False, mmsi=None, include_dac_fi=True):
        '''@param include_bin_hdr: If true, include the standard message header with source mmsi'''
        bvList = []
        if include_bin_hdr:
            bvList.append( binary.setBitVectorSize( BitVector(intVal=8), 6 ) ) # Messages ID
            bvList.append( binary.setBitVectorSize( BitVector(intVal=0), 2 ) ) # Repeat Indicator
            if mmsi is not None:
                bvList.append( binary.setBitVectorSize( BitVector(intVal=mmsi), 30 ) )
            elif self.source_mmsi is not None:
                bvList.append( binary.setBitVectorSize( BitVector(intVal=self.source_mmsi), 30 ) )
            else:
                print ('WARNING: using a default mmsi')
                bvList.append( binary.setBitVectorSize( BitVector(intVal=999999999), 30 ) )

        if include_bin_hdr or include_dac_fi:
            bvList.append( BitVector( bitstring = '00' ) ) # Should this be here or in the bin_hdr?
            bvList.append( binary.setBitVectorSize( BitVector(intVal=self.dac), 10 ) )
            bvList.append( binary.setBitVectorSize( BitVector(intVal=self.fi), 6 ) )

        bvList.append( binary.setBitVectorSize( BitVector(intVal=self.link_id), 10 ) )
        bvList.append( binary.setBitVectorSize( BitVector(intVal=self.area_type), 7 ) )

        bvList.append( binary.setBitVectorSize( BitVector(intVal=self.when.month), 4 ) )
        bvList.append( binary.setBitVectorSize( BitVector(intVal=self.when.day), 5 ) )
        bvList.append( binary.setBitVectorSize( BitVector(intVal=self.when.hour), 5 ) )
        #sys.stderr.write('HOUR_ENCODING: %d -> %s -> %d' % (self.when.hour, bvList[-1], int(bvList[-1])) )
        bvList.append( binary.setBitVectorSize( BitVector(intVal=self.when.minute), 6 ) )

        bvList.append( binary.setBitVectorSize( BitVector(intVal=self.duration), 18 ) )

        #stdlen = sum([len(b) for b in bvList])

        #print ('pre_adding_areas:',len(bvList))
        #for i in range(len(bvList)):
        #    print (i,len(bvList[i]))
        #print ('About to encode',len(self.areas),'areas')

        for i,area in enumerate(self.areas):
            bvList.append(area.get_bits())
            #print ('\tsubarea:',i,len(bvList[-1]))

        bv = binary.joinBV(bvList)
        if len(bv) > 953:
            raise AisPackingException('message to large.  Need %d bits, but can only use 953' % len(bv) )
        return bv

#    def get_fetcher_formatter(self):
#        '''return string for USCG/Alion fetcher formatter'''
#        pass

    def decode_nmea(self, strings):
        '''unpack nmea instrings into objects.
        The strings will be aggregated into one message
        '''
        for msg in strings:
            #print ('msg_decoding:',msg)
            #print ('type:',type(ais_nmea_regex), type(ais_nmea_regex.search(msg)))
            msg_dict = ais_nmea_regex.search(msg).groupdict()

            if  msg_dict['checksum'] != nmea_checksum_hex(msg):
                raise AisUnpackingException('Checksum failed')

        try: 
            msgs = [ais_nmea_regex.search(line).groupdict() for line in strings]
        except AttributeError:
            raise AisUnpackingException('one or more NMEA lines did were malformed (1)' )
        if None in msgs:
            raise AisUnpackingException('one or more NMEA lines did were malformed')

        bits = []
        #print 'len_msgs:',len(msgs)
        for msg in msgs:
            msg['fill_bits'] = int(msg['fill_bits'])
            bv = binary.ais6tobitvec(msg['body'])
            if int(msg['fill_bits']) > 0:
                bv = bv[:-msg['fill_bits']]
            bits.append(bv)
        bits = binary.joinBV(bits)
        self.decode_bits(bits)

    def decode_bits(self, bits):
        '''decode the bits for a message'''

        #print 'decode_all_bits:',bits
        r = {}
        r['message_id']       = int( bits[:6] )
	r['repeat_indicator'] = int(bits[6:8])
	r['mmsi']             = int( bits[8:38] )
        r['spare']            = int( bits[38:40] )
        r['dac']       = int( bits[40:50] )
        r['fi']        = int( bits[50:56] )
        r['link_id']   = int( bits[56:66] )
        r['area_type'] = int( bits[66:73] )
        r['utc_month'] = int( bits[73:77] )
        r['utc_day']   = int( bits[77:82] )
        r['utc_hour']  = int( bits[82:87] )
        r['utc_min']   = int( bits[87:93] )
        r['duration_min'] = int( bits[93:111] )
        r['sub_areas'] = []
        #print r

        self.area_type = r['area_type']

        # FIX: handle Dec - Jan transition / year roll over
        now = datetime.datetime.utcnow()
        self.when = datetime.datetime(year=now.year, month=r['utc_month'], day=r['utc_day'],
                                      hour=r['utc_hour'], minute=r['utc_min'])
        self.duration = r['duration_min']
        self.link_id = r['link_id']

        self.dac = r['dac']
        self.fi = r['fi']

        # AIVDM data
        self.message_id = r['message_id']
        self.repeat_indicator = r['repeat_indicator']
        self.source_mmsi = r['mmsi'] # This will probably get ignored

        sub_areas_bits = bits[111:]
        del bits  # be safe

        # Messages might be padded up to 7 bits to byte align the message, but no more
        assert 8 > len(sub_areas_bits) % SUB_AREA_SIZE

        #print ('sub_area_len:', len(sub_areas_bits), len(sub_areas_bits) % SUB_AREA_SIZE)
        #print ('num_sub_areas:', len(sub_areas_bits) / SUB_AREA_SIZE)
        #shapes = self.get_shapes(sub_areas_bits)

        #print '\nshapes:', shapes

        for i in range(len(sub_areas_bits) / SUB_AREA_SIZE):
            bits = sub_areas_bits[ i*SUB_AREA_SIZE : (i+1)*SUB_AREA_SIZE ]
            #print bits
            #print bits[:3]
            sa_obj = self.subarea_factory(bits=bits)
            #print 'obj:', str(sa_obj)
            self.add_subarea(sa_obj)

    def get_shapes(self,sub_areas_bits):
        'return a list of the sub area types'
        shapes = []
        for i in range(len(sub_areas_bits) / SUB_AREA_SIZE):
            bits = sub_areas_bits[ i*SUB_AREA_SIZE : (i+1)*SUB_AREA_SIZE ]
            shape = int( bits[:3] )
            shapes.append((shape, shape_types[shape]))
        return shapes

    def subarea_factory(self,bits):
        'scary side effects going on in this with Polyline and Polygon'
        shape = int( bits[:3] )
        #print ('subarea_factory', len(self.areas), 'shape:',shape)
        if   0 == shape: return AreaNoticeCirclePt(bits=bits)
        elif 1 == shape: return AreaNoticeRectangle(bits=bits)
        elif 2 == shape: return AreaNoticeSector(bits=bits)

        elif 3 == shape: # Polyline
            # There has to be a point or line before the polyline to give the starting lon and lat
            assert len(self.areas) > 0
            lon = None
            lat = None
            #print 'previous:',type(self.areas[-1])
            if isinstance(self.areas[-1], AreaNoticeCirclePt):
                lon = self.areas[-1].lon
                lat = self.areas[-1].lat
                self.areas.pop()
            elif isinstance(self.areas[-1], AreaNoticePolyline):
                print ('FIX: check multi packet polyline', self.areas[-1].geom)
                last_pt = self.areas[-1].get_points[-1]
                lon = last_pt[0]
                lat = last_pt[1]
            else:
                raise AisPackingException('Point or another polyline must preceed a polyline')
            return AreaNoticePolyline(bits=bits, lon=lon, lat=lat)

        elif 4 == shape:
            assert len(self.areas) > 0
            lon = lat = None
            if isinstance(self.areas[-1], AreaNoticeCirclePt):
                lon = self.areas[-1].lon
                lat = self.areas[-1].lat
                self.areas.pop()
            elif isinstance(self.areas[-1], AreaNoticePolyline):
                print ('FIX: check multi packet polyline', self.areas[-1].geom)
                last_pt = self.areas[-1].get_points[-1]
                lon = last_pt[0]
                lat = last_pt[1]
            return AreaNoticePolygon(bits=bits, lon=lon, lat=lat)
        elif 5 == shape:
            assert len(self.areas) > 0
            assert not isinstance(self.areas[0], AreaNoticeFreeText) # As long as we have at least one geom, we are good
            # FIX: can free text come before the geometry?
            return AreaNoticeFreeText(bits=bits)
        else:
            sys.stderr.write('Warning: unknown shape type %d' % shape )
            return None # bad bits?

sbnms_bbox = {
    'ur': ( -68.3, 43.0 ),
    'll': ( -71.3, 41.0 ),
}

# WARNING: the fetcher formatter message is a brittle design.
def message_2_fetcherformatter(msg,  # An area notice or any other child of BBM that response to get bits
                             magic_number='BMS', #Always the first string
                             site_name='SBNMS',  # Area name
                             xmin=-71.3, xmax=-68.3,
                             ymin=41.0, ymax=43.0,
                             link_id=None,  # Station / Zone / Area ID.  Buoy number
                             message_type=None, # for Zone/Area, this is 1000 + notice description field
                             priority=0, # 0 - no priority, 10 highest priority
                             timestamp=None, # unix UTC seconds timestamp
                             verbose=False
                             ):
    'Take an AreaNotice and produce a Fetcher Formatter CSV'
    v = verbose

    if v:
        print ('message_2_fetcherformatter:',str(msg))

    if timestamp is None:
        timestamp=int(time.time())
    elif isinstance(timestamp,datetime.datetime):
        timestamp = calendar.timegm(datetime.datetime.utctimetuple(timestamp))

    timestamp += 24*3600
    if v:
        print ('Moving time up by 4 hours to deal with Windows time coding issues...')
        print ('\t\tEDT is 4 to 5 hours off utc')
        print ('\t\t24 hours means this code will work anywhere in the world with windows timezone troubles')

    if message_type is None:
        if isinstance(msg,AreaNotice):
            message_type = msg.area_type
        else:
            raise NotImplmented

    if isinstance(msg,AreaNotice):
        if message_type < 1000:
            # AreaNotice message type has to be greater than 1000
            message_type += 1000
    # if not isinstance(msg,EnvMessage) and isinstance(msg,AreaNotice):
    #     # This mechanism is only defined for these two IMO Circ 289 messages
    #     assert False

    if link_id == None:
        link_id = msg.link_id
   
    dac = BitVector(intVal=msg.dac, size=10)
    fi  = BitVector(intVal=msg.fi,  size=6)

    dacfi = dac+fi
    bits = msg.get_bits(include_dac_fi=False)
    if v:
        print ('dacfi:',str(dacfi))
        print ('bits: len=',len(bits),' ... ',str(bits))

    line = [magic_number,site_name,
            xmin,ymax,xmax,ymin,
            link_id,message_type,priority,timestamp,dacfi,bits]

    # if v:
    #     for item in [str(item) for item in line]:
    #         print ('\t',str(item))

    return ','.join([str(item) for item in line])


class NormQueue(Queue.Queue):
    '''Normalized AIS messages that are multiple lines

    - works based USCG dict representation of a line that comes back from the regex.
    - not worrying about the checksum.  Assume it already has been validated
    - 160 stations in the US with 10 seq channels... should not be too much data
    - assumes each station will send in order messages without duplicates
    '''
    def __init__(self, separator='\n', maxsize=0, verbose=False):
        self.input_buf = ''
        self.v = verbose
        self.separator = separator
        self.stations = {}

        Queue.Queue.__init__(self,maxsize)

    def put(self, msg):
        if not isinstance(msg, dict): raise TypeError('Message must be a dictionary')

        total = int(msg['total'])
        station = msg['station']
        if station not in self.stations:
            self.stations[station] = {0:[ ],1:[ ],2:[ ],3:[ ],4:[ ],
                                      5:[ ],6:[ ],7:[ ],8:[ ],9:[ ]}

        if total == 1:
            Queue.Queue.put(self,msg) # EASY case
            return

        seq = int(msg['seq_id'])
        sen_num = int(msg['sen_num'])

        if sen_num == 1:
            # Flush that station's seq and start it with a new msg component
            self.stations[station][seq] = [msg['body'],] # START
            return

        if sen_num != len(self.stations[station][seq]) + 1:
            self.stations[station][seq] = [ ] # DROP and flush... bad seq
            return
        
        if sen_num == total:
            msgs = self.stations[station][seq]
            self.stations[station][seq] = [ ] # FLUSH
            if len(msgs) != total - 1:
                return # INCOMPLETE was missing part - so just drop it

            # all parts should have the same metadata, but last has the fill bits
            msg['body'] = ''.join(msgs) + msg['body']
            msg['total'] = msg['seq_num'] = 1
            Queue.Queue.put(self,msg)
            return
        
        self.stations[station][seq].append(msg['body']) # not first, not last

    
def main():
    from optparse import OptionParser
    parser = OptionParser(usage="%prog [options]",version="%prog "+__version__)
    
    # outputChoices = ('std',) #,'html','csv','sql' , 'kml','kml-full')
    # parser.add_option('-T','--output-type',choices=outputChoices,type='choice',dest='outputType'
    #                   ,default=outputChoices[0]
    #                   ,help='What kind of string to output ('+', '.join(outputChoices)+') [default: %default]')

    (options,args) = parser.parse_args()
    #for arg in args:
    #    print 'Trying:',arg
    norm_queue = NormQueue()

    kmlfile = open('out.kml','w')
    kmlfile.write(kml_head)
    kmlfile.write(file('areanotice_styles.kml').read())
    
    if 0==len(args):
        # Assume stdin
        assert False
    if '!AIVDM' in args[0]:
        an = AreaNotice(nmea_strings=args)
        print ('Area Notice:',str(an))
    else:
        # Assume these are files
        
        for filename in args:
            
            for line in open(filename):
                #print ('line:',line.strip())
                try:
                    match = ais_nmea_regex.search(line).groupdict()
                except AttributeError:
                    if 'AIVDM' in line: print ('BAD_MATCH:',line)
                    continue


                norm_queue.put(match)
                if norm_queue.qsize()>0:
                    msg = norm_queue.get(False)
                    if msg['body'][0] != '8':
                        #print ('skipping non-8')
                        continue
                    #print ('msg:', msg)
                    nmea = '!AIVDM,1,1,,A,{body},{fill_bits}*{{checksum}},{station},{time_stamp}'.format(**msg)
                    #print ('nmea:',nmea)
                    checksum = nmea_checksum_hex(nmea)
                    #print ('checksum: "%s"',checksum)
                    nmea = nmea.format(checksum=checksum)
                    #print ('nmea:',nmea)
                    #try:
                    area_notice = AreaNotice(nmea_strings=(nmea,))
                    print ('AreaNotice:',area_notice)
                    kmlfile.write(area_notice.kml(with_style=True, with_time=True, with_extended_data=True))
                    

    kmlfile.write(kml_tail)

    
if __name__=='__main__':
    main()
