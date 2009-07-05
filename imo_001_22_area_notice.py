#!/usr/bin/env python
__author__    = 'Kurt Schwehr'
__version__   = '$Revision: 4799 $'.split()[1]
__revision__  = __version__ # For pylint
__date__ = '$Date: 2006-09-25 11:09:02 -0400 (Mon, 25 Sep 2006) $'.split()[1]
__copyright__ = '2009'
__license__   = 'GPL v3'
__contact__   = 'kurt at ccom.unh.edu'

__doc__ ='''
Trying to do a more sane design for AIS BBM message

@requires: U{Python<http://python.org/>} >= 2.5
@requires: U{epydoc<http://epydoc.sourceforge.net/>} >= 3.0.1
@requires: U{lxml<http://codespeak.net/lxml/lxmlhtml.html>} >= 2.0
@requires: U{shapely<http:///>}
@requires: U{geojson<http:///>}
@requires: U{BitVector<http:///>}
@requires: U{BitVector<http:///>}
@requires: U{pyproj<http:///>}

@license: GPL v3
@undocumented: __doc__
@since: 2009-Jun-01
@status: under development
@organization: U{CCOM<http://ccom.unh.edu/>} 
'''

# http://blog.lucanatali.it/2006/12/nmea-checksum-in-python.html

import sys
#from decimal import Decimal
import datetime
from operator import xor # for checksum

import operator
#from math import *
import math

from pyproj import Proj
import shapely.geometry
import geojson

import lxml
from lxml.html import builder as E

from BitVector import BitVector

import binary, aisstring

def lon_to_utm_zone(lon):
    return int(( lon + 180 ) / 6) + 1

iso8601_timeformat = '%Y-%m-%dT%H:%M:%SZ'
'''ISO time format for NetworkLinkControl strftime
@see: U{KML Tutorial<http://code.google.com/apis/kml/documentation/kml_21tutorial.html#updates>}
'''


nmea_talkers = {
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
    'cau_mammals_not_obs': 0,
    'cau_mammals_reduce_speed': 1,
    'cau_mammals_stay_clear': 2,
    'cau_mammals_report_sightings': 3,
    'cau_habitat_reduce_speed': 4,
    'cau_habitat_stay_clear': 5,
    'cau_habitat_no_fishing_or_anchoring': 6,
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
    'info_pilot_boarding': 88,
    'info_icebreaker_staging': 89,
    'info_refuge': 90,
    'info_pos_icebreakers': 91,
    'info_pos_response_units': 92,
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
    'report_of_see_text': 114,
    'other_see_text': 125,
    'cancel_area_notice': 126,
    'undefined': 127,
    0: 'Caution Area: Marine mammals NOT observed',
    1: 'Caution Area: Marine mammals in area - Reduce Speed',
    2: 'Caution Area: Marine mammals in area - Stay Clear',
    3: 'Caution Area: Marine mammals in area - Report Sightings',
    4: 'Caution Area: Protected Habitat - Reduce Speed',
    5: 'Caution Area: Protected Habitat - Stay Clear',
    6: 'Caution Area: Protected Habitat - No fishing or anchoring',
    7: 'Reserved',
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
    38: 'Reserved',
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
    84: 'Reserved',
    85: 'Reserved',
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
    113: 'Reserved',
    114: 'Report from ship: Miscellaneous information - define in free text field',
    115: 'Reserved',
    116: 'Reserved',
    117: 'Reserved',
    118: 'Reserved',
    119: 'Reserved',
    120: 'Reserved',
    121: 'Reserved',
    122: 'Reserved',
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

def _make_short_notice():
    d = {}
    for k,v in notice_type.iteritems():
        if isinstance (k,str):
            d[v] = k
    return d

short_notice = _make_short_notice()

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

def deg2rad(degrees):
    return (degrees / 180.) * math.pi
def rad2deg(radians):
    return (radians / math.pi) * 180.

def geom2kml(geom_dict):
    '''Convert a geointerface geometry to KML
    
    @param geo_dict: Dictionary containing 'geometry' as defined by the geo interface / geojson / shapely
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



class AisException(Exception):
    pass

class AisPackingException(AisException):
    def __init__(self, fieldname, value):
        self.fieldname = fieldname
        self.value = value
    def __repr__(self):
        return "Validation on %s failed (value %s) while packing" % (self.fieldname, self.value)

class AisUnpackingException(AisException):
    def __init__(self, fieldname, value):
        self.fieldname = fieldname
        self.value = value
    def __repr__(self):
        return "Validation on %s failed (value %s) while unpacking" % (self.fieldname, self.value)



def nmea_checksum_hex(sentence):
    nmea = map(ord, sentence.split('*')[0])
    checksum = reduce(xor, nmea)
    #print 'checksum:',checksum, hex(checksum)
    return hex(checksum).split('x')[1].upper()

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

        #print '\naivdm_header:',message_id,repeat_indicator,source_mmsi
        bvList = []
	bvList.append(binary.setBitVectorSize(BitVector(intVal=message_id),6))
        bvList.append(binary.setBitVectorSize(BitVector(intVal=repeat_indicator),2))
        bvList.append(binary.setBitVectorSize(BitVector(intVal=source_mmsi),30))
        return binary.joinBV(bvList)

# See __geo_interface__
#    def get_json(self):
#        'Child classes must implement this.  Return a json object'
#        raise NotImplementedError()

    def get_aivdm(self, sequence_num = None, channel = 'A', normal_form=False, source_mmsi=None, repeat_indicator=None):
        '''return the nmea string as if it had been received.  Assumes that payload_bits has already been set
        @param sequence_num: Which channel of AIVDM on the local serial line (in 0..9)
        @param channel: VHF radio channel ("A" or "B")
        @param normal_form:  Set to true to always return aone line NMEA message.  False allows multi-sentence messages
        @return: AIVDM sentences
        @rtype: list (even for normal_form for consistency)
        '''
        if sequence_num is not None and (sequence_num <= 0 or sequence_num >= 9):
            raise AisPackingException('sequence_num',sequence_num)
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
        payload, pad = binary.bitvectoais6(header + self.get_bits())

        if sequence_num is None:
            sequence_num = ''
        
        if normal_form:
            # Build one big NMEA string no matter what
            sentence = '!AIVDM,{tot_sentences},{sentence_num},{sequence_num},{channel},{payload},{pad}'.format(
                tot_sentences=1, sentence_num=1,
                sequence_num=sequence_num, channel=channel,
                payload=payload, pad=pad
                )
            return [sentence + '*' + nmea_checksum_hex(sentence),]

        max_payload_char = 43
        #if sequence_num == '':
        #    max_payload_char = 44 # is this safe?

        sentences = []
        tot_sentences = 1 + len(payload) / max_payload_char
        sentence_num = 0
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

    def kml(self,with_style=False,full=False,with_time=False):
        '''return kml str for google earth
        @param style: if style is True, it will use the standard style.  Set to a name for a custom style
        '''
        o = []
        if full:
            o.append('''<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2" xmlns:gx="http://www.google.com/kml/ext/2.2" xmlns:kml="http://www.opengis.net/kml/2.2" xmlns:atom="http://www.w3.org/2005/Atom">
<Document>
''')
            o.append(file('areanotice_styles.kml').read())
        html = self.html()
        for area in self.areas:
            geo_i = area.__geo_interface__
            if 'geometry' not in geo_i:
                print 'Skipping area:',str(area)
                continue
            #print 'geo_i:',geo_i
            #print 'type:',geo_i['geometry']
            #print 'type:',geo_i['geometry']['type']
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
                # no style available
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
            o.append('''</Document>
</kml>
''')

        return '\n'.join(o)


class m5_shipdata(AIVDM):
    'Junk used for initial testing'
    def __init__(self, repeat_indicator = None, source_mmsi = None):
        AIVDM.__init__(self,5,repeat_indicator,source_mmsi)

    def get_bits(self):
        print 'm5 get_bits'
        return binary.ais6tobitvec('55OhdP020db0pM92221E<q>0M8510hF22222220S4pW<;40Htwh00000000000000000000')[:-2] # remove pad

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

    def get_bbm(self, talker='EC', sequence_num = None, channel = 'A'):
        if not isinstance(talker,str) or len(talker) != 2:
            AisPackingException('talker',talker)
        if sequence_num is not None and (sequence_num <= 0 or sequence_num >= 9):
            raise AisPackingException('sequence_num',sequence_num)
        if channel not in ('A','B'):
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

class BbmMsgTest(BBM):
    def get_bits(self):
        print 'BbmMsgTest get_bits'
        return binary.ais6tobitvec('85OhdP020db0p')[:-2] # remove pad

class AreaNoticeSubArea(object):
    pass

class AreaNoticeCirclePt(AreaNoticeSubArea):
    area_shape = 0
    def __init__(self, lon=None, lat=None, radius=0, bits=None):
        '''@param radius: 0 is a point, otherwise less than or equal to 409500m.  Scale factor is automatic
        @param bits: string of 1's and 0's or a BitVector
        '''
        if lon is not None:
            assert lon >= -180. and lon <= 180.
            self.lon = lon
            assert lat >= -90. and lat <= 90.
            self.lat = lat

            assert radius >= 0 and radius < 409500
            self.radius = radius

            if radius / 100. >= 4095:
                self.scale_factor_raw = 3
            elif radius / 10. > 4095:
                self.scale_factor_raw = 2
            elif radius > 4095:
                self.scale_factor_raw = 1
            else:
                self.scale_factor_raw = 0

            self.scale_factor = (1,10,100,100)[self.scale_factor_raw]
            self.radius_scaled = radius / self.scale_factor
            return

        elif bits is not None:
            decode_bits(bits)
            return

        return # Return an empty object


    def decode_bits(bits):
        if len(bits) != 90: raise AisUnpackingException('bit length',len(bits))
        if isinstance(bits,str):
            bits = BitVector(bitstring = bits)
        elif isinstance(bits, list) or isinstance(bits,tuple):
            bits = BitVector ( bitlist = bits)

        self.area_shape = int( bits[:3] )
        self.scale_factor_raw = int( bits[3:5] )
        self.scale_factor = (1,10,100,1000)[self.scale_factor_raw]
        self.lon = binary.signedIntFromBV( bits[ 5:33] ) / 600000
        self.lat = binary.signedIntFromBV( bits[33:60] ) / 600000
        self.radius_scaled = int( bits[60:72] )

        self.radius = self.radius_scaled * self.scale_factor

        spare = int( bits[72:90] )
        #assert 0 == spare
        

    def get_bits(self):
        'Build a BitVector for this area'
        bvList = []
        bvList.append( binary.setBitVectorSize( BitVector(intVal=0), 3 ) ) # area_shape/type = 0
        #print self.scale_factor
        #scale_factor = {1:0,10:1,100:2,1000:3}[self.scale_factor]
        bvList.append( binary.setBitVectorSize( BitVector(intVal=scale_factor_raw), 2 ) )
        bvList.append( binary.bvFromSignedInt( int(self.lon*600000), 28 ) )
        bvList.append( binary.bvFromSignedInt( int(self.lat*600000), 27 ) )
        bvList.append( binary.setBitVectorSize( BitVector(intVal=self.radius_scaled), 12 ) )
        bvList.append( binary.setBitVectorSize( BitVector(intVal=0), 18 ) ) # spare
        bv = binary.joinBV(bvList)
        assert 90==len(bv)
        return bv

    def __unicode__(self):
        if self.radius == 0.:
            return 'AreaNoticeCirclePt: Point at (%.4f,%.4f)' % (self.lon,self.lat)
        return 'AreaNoticeCirclePt: Circle centered at (%.4f,%.4f) - radius %dm' % (self.lon,self.lat,self.radius)

    def __str__(self):
        return self.__unicode__()

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


        if self.radius == 0.:
            return {'area_shape': self.area_shape, 
                    'area_shape_name': 'point',
                    'geometry': {'type': 'Point', 'coordinates': [self.lon, self.lat] }
                    }

        # self.radius > 0 ... circle
        r = {
            'area_shape': self.area_shape, 
            'area_shape_name': 'circle',
            'radius':self.radius,
            'geometry': {'type': 'Polygon', 'coordinates': tuple(self.geom().boundary.coords) },
            #'geometry': {'type': 'Polygon', 'coordinates': [pt for pt in self.geom().boundary.coords]},
            # Leaving out scale_factor
            }
        return r

class AreaNoticeRectangle(AreaNoticeSubArea):
    area_shape = 1
    def __init__(self, lon=None, lat=None, east_dim=0, north_dim=0, orientation_deg=0, bits=None):
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

            assert 0 <=  east_dim and  east_dim <= 25500
            assert 0 <= north_dim and north_dim <= 25500

            assert 0 <= orientation_deg and orientation_deg < 360

            if east_dim / 1000. >= 255 or north_dim / 1000. >= 255:
                self.scale_factor = 1000
                self.scale_factor_raw = 3

            elif east_dim / 100. >= 255 or north_dim / 100. >= 255:
                self.scale_factor = 100
                self.scale_factor_raw = 2

            elif east_dim / 10. >= 255 or north_dim / 10. >= 255:
                self.scale_factor = 10
                self.scale_factor_raw = 1
            else:
                self.scale_factor = 1
                self.scale_factor_raw = 0

            self.e_dim = east_dim
            self.n_dim = north_dim
            self.e_dim_scaled = east_dim / self.scale_factor
            self.n_dim_scaled = east_dim / self.scale_factor

            self.orientation_deg = orientation_deg
            #self.orient_rad = deg2rad(orientation)

        elif bits is not None:
            self.decode_bits(bits)

    def decode_bits(bits):
        if len(bits) != 90: raise AisUnpackingException('bit length',len(bits))
        if isinstance(bits,str):
            bits = BitVector(bitstring = bits)
        elif isinstance(bits, list) or isinstance(bits,tuple):
            bits = BitVector ( bitlist = bits)

        self.area_shape = int( bits[:3] )
        self.scale_factor = int( bits[3:5] )
        self.lon = binary.signedIntFromBV( bits[ 5:33] ) / 600000
        self.lat = binary.signedIntFromBV( bits[33:60] ) / 600000
        self.e_dim_scaled = int ( bits[60:68] ) 
        self.n_dim_scaled = int ( bits[68:76] ) 

        self.e_dim = self.e_dim_scaled * (1,10,100,100)[self.scale_factor]
        self.n_dim = self.n_dim_scaled * (1,10,100,100)[self.scale_factor]

        self.orientation_deg = int ( bits[76:85] )

        self.spare = int ( bits[85:90] )

    def get_bits(self):
        bvList = []
        bvList.append( binary.setBitVectorSize( BitVector(intVal=0), 3 ) ) # area_shape/type = 0
        #xsscale_factor = {1:0,10:1,100:2,1000:3}[self.scale_factor]
        bvList.append( binary.setBitVectorSize( BitVector(intVal=scale_factor_raw), 2 ) )
        bvList.append( binary.bvFromSignedInt( int(self.lon*600000), 28 ) )
        bvList.append( binary.bvFromSignedInt( int(self.lat*600000), 27 ) )
        bvList.append( binary.setBitVectorSize( BitVector(intVal=self.e_dim_scaled), 8 ) )
        bvList.append( binary.setBitVectorSize( BitVector(intVal=self.n_dim_scaled), 8 ) )
        bvList.append( binary.setBitVectorSize( BitVector(intVal=self.orientation), 9 ) )
        bvList.append( binary.setBitVectorSize( BitVector(intVal=0), 5 ) ) # spare
        bv = binary.joinBV(bvList)
        assert 90==len(bv)
        return bv
    
    def __unicode__(self):
        return 'AreaNoticeRectangle: (%.4f,%.4f) [%d,%d]m rot: %d deg' % (self.lon,self.lat,self.e_dim,self.n_dim,self.orientation_deg)

    def __str__(self):
        return self.__unicode__()


    def geom(self):
        'return shapely geometry object'
        zone = lon_to_utm_zone(self.lon)
        params = {'proj':'utm', 'zone':zone}
        proj = Proj(params)

        p1 = proj(self.lon,self.lat)

        pts = [(0,0), (self.e_dim,0), (self.e_dim,self.n_dim), (0,self.n_dim)]

        #print 'before:',pts
        rot = deg2rad(-self.orientation_deg)
        pts = [vec_rot(pt,rot) for pt in pts]
        #print 'rot:',pts

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
    def __init__(self, lon=None, lat=None, radius=0, left_bound_deg=0, right_bound_deg=0, bits=None):
        '''
        A pie slice

        @param lon: WGS84 longitude
        @param lat: WGS84 latitude
        @param radius: width in meters
        @param left_bound_deg: Orientation of the left boundary.  CW from True North
        @param right_bound_deg: Orientation of the right boundary.  CW from True North

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

            assert 0 <=  radius and  radius <= 25500

            assert 0 <=  left_bound_deg and  left_bound_deg < 360
            assert 0 <= right_bound_deg and right_bound_deg < 360

            assert left_bound_deg <= right_bound_deg

            if radius / 100. >= 4095: self.scale_factor_raw = 3
            elif radius / 10. > 4095: self.scale_factor_raw = 2
            elif radius > 4095:       self.scale_factor_raw = 1
            else:                     self.scale_factor_raw = 0
            self.scale_factor = (1,10,100,100)[self.scale_factor_raw]
            self.radius = radius
            self.radius_scaled = int( radius / self.scale_factor)

            self.left_bound_deg  = left_bound_deg
            self.right_bound_deg = right_bound_deg

        elif bits is not None:
            self.decode_bits(bits)
       
    def decode_bits(bits):
        if len(bits) != 90: raise AisUnpackingException('bit length',len(bits))
        if isinstance(bits,str):
            bits = BitVector(bitstring = bits)
        elif isinstance(bits, list) or isinstance(bits,tuple):
            bits = BitVector ( bitlist = bits)

        self.area_shape = int( bits[:3] )
        self.scale_factor = int( bits[3:5] )
        self.lon = binary.signedIntFromBV( bits[ 5:33] ) / 600000
        self.lat = binary.signedIntFromBV( bits[33:60] ) / 600000
        self.radius_scaled = int ( bits[60:72] ) 

        self.radius = self.radius_scaled * (1,10,100,100)[self.scale_factor]

        self.left_bound_deg = int ( bits[72:81] )
        self.right_bound_deg = int ( bits[81:90] )

    def __unicode__(self):
        return 'AreaNoticeSector: (%.4f,%.4f) %d rot: %d to %d deg' % (self.lon, self.lat, self.radius, 
                                                                       self.left_bound_deg, self.right_bound_deg)
    def __str__(self):
        return self.__unicode__()


    def geom(self):
        'return shapely geometry object'
        zone = lon_to_utm_zone(self.lon)
        params = {'proj':'utm', 'zone':zone}
        proj = Proj(params)

        # FIX: test for degenerate shapes

        p1 = proj(self.lon,self.lat)

        pts = [ vec_rot( (0,self.radius), deg2rad(-angle) ) for angle in frange(self.left_bound_deg, self.right_bound_deg+0.01, 0.5) ]
        pts = [(0,0),] + pts + [(0,0),]
        print 'pts:',pts


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

        @param points: 1 to 4 relative offsets (angle in degrees, distance in meters) 
        @param lon: WGS84 longitude of the starting point.  Must match the previous point
        @param lat: WGS84 longitude of the starting point.  Must match the previous point
        @param bits: bits to decode from
        @todo: FIX: make sure that the AreaNotice decode bits passes the lon, lat
        '''

        if lon is not None:
            assert lon >= -180. and lon <= 180.
            self.lon = lon
            assert lat >= -90. and lat <= 90.
            self.lat = lat


        if points is not None:
            assert len(points)>0 and len(points)<5
            self.points = points

            max_dist = max([pt[1] for pt in points])
            if max_dist / 100. >= 4095: self.scale_factor_raw = 3
            elif max_dist / 10. > 4095: self.scale_factor_raw = 2
            elif max_dist > 4095:       self.scale_factor_raw = 1
            else:                     self.scale_factor_raw = 0
            self.scale_factor = (1,10,100,100)[self.scale_factor_raw]

        elif bits is not None:
            self.decode_bits(bits)

    def decode_bits(bits):
        if len(bits) != 90: raise AisUnpackingException('bit length',len(bits))
        if isinstance(bits,str):
            bits = BitVector(bitstring = bits)
        elif isinstance(bits, list) or isinstance(bits,tuple):
            bits = BitVector ( bitlist = bits)

        self.area_shape = int( bits[:3] )
        self.scale_factor = int( bits[3:5] )

        self.points = []
        for i in range(4):
            base = 5 + i*21
            angle = int ( bits[base:base+10] )
            dist_scaled = int ( bits[base+10:base+10+11] )
            dist = dist_scaled * (1,10,100,100)[self.scale_factor]
            self.points.append((angle,dist))
            if 720 == dist_scaled:
                break


    def get_bits(self):
        'Build a BitVector for this area'
        bvList = []
        bvList.append( binary.setBitVectorSize( BitVector(intVal=0), 3 ) ) # area_shape/type = 0

        bvList.append( binary.setBitVectorSize( BitVector(intVal=scale_factor_raw), 2 ) )

        assert(False) # FIX: write

        bv = binary.joinBV(bvList)
        assert 90==len(bv)
        return bv

    def __unicode__(self):
        return 'AreaNoticePolyline: (%.4f,%.4f) %d points' % ( self.lon, self.lat, len(self.points) )

    def __str__(self):
        return self.__unicode__()

    def geom(self):
        zone = lon_to_utm_zone(self.lon)
        params = {'proj':'utm','zone':zone}
        proj = Proj(params)

        p1 = proj(self.lon,self.lat)

        pts = [(0,0)]
        cur = (0,0)
        for pt in self.points:
            alpha = deg2rad(pt[0])
            d = pt[1]
            x,y = d * math.sin(alpha), d * math.cos(alpha)
            cur = vec_add(cur,(x,y))
            #print 'step:',pt,cur
            pts.append(cur)


        pts = [vec_add(p1,pt) for pt in pts]
        pts = [proj(*pt,inverse=True) for pt in pts]
        return shapely.geometry.LineString(pts)

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
    'Polyline that wraps back to the beginning'
    area_shape = 4
    area_name = 'polygon'

    def geom(self):
        zone = lon_to_utm_zone(self.lon)
        params = {'proj':'utm','zone':zone}
        proj = Proj(params)

        p1 = proj(self.lon,self.lat)

        pts = [(0,0)]
        cur = (0,0)
        for pt in self.points:
            alpha = deg2rad(pt[0])
            d = pt[1]
            x,y = d * math.sin(alpha), d * math.cos(alpha)
            cur = vec_add(cur,(x,y))
            pts.append(cur)


        print 'pts:',pts

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
    area_shape = 4
    area_name = 'freetext'
    def __init__(self,text=None, bits=None):
        if text is not None:
            text = text.upper()
            assert len(text) < 84
            for c in text:
                assert c in aisstring.characterDict
            self.text = text
        elif bits is not None:
            self.decode_bits(bits)

           
    def decode_bits(bits):
        if len(bits) != 90: raise AisUnpackingException('bit length',len(bits))
        if isinstance(bits,str):
            bits = BitVector(bitstring = bits)
        elif isinstance(bits, list) or isinstance(bits,tuple):
            bits = BitVector ( bitlist = bits)

        area_shape = int( bits[:3] )
        assert self.area_shape == area_shape
        self.text = aisstring.decode(bits[3:-1])
        self.spare = int(bits[-1])

    def get_bits(self):
        'Build a BitVector for this area'
        bvList = []
        bvList.append( binary.setBitVectorSize( BitVector(intVal=0), self.area_shape ) )
        bvList.append(aisstring.encode(self.text,8))
        bvList.append( BitVector(intVal=1) ) # spare
        bv = binary.joinBV(bvList)
        assert 90==len(bv)
        return bv

    def __unicode__(self):
        return 'AreaNoticeFreeText: "%s"' % (self.text,)

    def __str__(self):
        return self.__unicode__()

    def geom(self):
        # FIX: should this somehow have a position?
        return None

    @property
    def __geo_interface__(self):
        'Provide a Geo Interface for GeoJSON serialization'
        # FIX: should this return geometry?  Probably not as this text gets built into the message text for other geom
        return {'area_shape': self.area_shape, 
                'area_shape_name': self.area_name,
                # No geometry... 'geometry': {'type': 'Point', 'coordinates': [self.lon, self.lat] }
                }

class AreaNotice(BBM):
    def __init__(self,area_type=None,when=None,duration=None,link_id=0, nmea_strings=None):
        '''
        @param area_type: 0..127 based on table 11.10
        @param when: when the notice starts
        @type when: datetime (UTC)
        @param duration: minutes for the notice to be in effect
        @param nmea_strings: Pass 1 or more nmea strings as a list
        '''
        if nmea_strings != None:
            self.decode_nmea(nmea_strings)

        elif area_type is not None and when is not None and duration is not None:
            # We are creating a new message
            assert area_type >= 0 and area_type <= 127
            self.area_type = area_type
            assert isinstance(when,datetime.datetime)
            self.when = when
            assert duration < 2**18 - 1 # Last number reserved for undefined... what does undefined mean?
            self.duration = duration
            self.link_id = link_id

            self.areas = []
        self.dac = 1
        self.fi = 22

        BBM.__init__(self, message_id = 8) # FIX: move to the beginning of this method

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
                'areas': []
                }
            }

        #print 'areas:',len(self.areas)
        #print 'bbm:',r['bbm']
        for area in self.areas:
            #print 'area_geo:',area.__geo_interface__
            r['bbm']['areas'].append(area.__geo_interface__)

        return r

    def add_subarea(self,area):
        assert len(self.areas) < 11
        self.areas.append(area)

    def get_bits(self,include_bin_hdr=False, mmsi=None, include_dac_fi=True):
        '''@param include_bin_hdr: If true, include the standard message header with source mmsi'''
        bvList = []
        if include_bin_hdr:
            bvList.append( binary.setBitVectorSize( BitVector(intVal=8), 6 ) ) # Messages ID
            bvList.append( binary.setBitVectorSize( BitVector(intVal=0), 2 ) ) # Repeat Indicator
            bvList.append( binary.setBitVectorSize( BitVector(intVal=mmsi), 30 ) )
            bvList.append( binary.setBitVectorSize( BitVector(intVal=0), 2 ) ) # Spare

        if include_dac_fi:
            bvList.append( binary.setBitVectorSize( BitVector(intVal=self.dac), 10 ) )
            bvList.append( binary.setBitVectorSize( BitVector(intVal=self.fi), 6 ) )

        bvList.append( binary.setBitVectorSize( BitVector(intVal=self.link_id), 10 ) )
        bvList.append( binary.setBitVectorSize( BitVector(intVal=self.area_type), 7 ) )

        bvList.append( binary.setBitVectorSize( BitVector(intVal=self.when.month), 4 ) )
        bvList.append( binary.setBitVectorSize( BitVector(intVal=self.when.day), 5 ) )
        bvList.append( binary.setBitVectorSize( BitVector(intVal=self.when.hour), 5 ) )
        bvList.append( binary.setBitVectorSize( BitVector(intVal=self.when.minute), 6 ) )

        bvList.append( binary.setBitVectorSize( BitVector(intVal=self.duration), 18 ) )

        #print '\narea_count:',len(self.areas)
        for area in self.areas:
            bvList.append(area.get_bits())

        return binary.joinBV(bvList)
           

#    def get_fetcher_formatter(self):
#        '''return string for USCG/Alion fetcher formatter'''
#        pass

def test():
    an = AreaNotice(0,datetime.datetime.utcnow(),24*60)
    

if __name__ == '__main__':
    test()


