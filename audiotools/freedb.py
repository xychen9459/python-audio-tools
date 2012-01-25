#!/usr/bin/python

#Audio Tools, a module and set of tools for manipulating audio data
#Copyright (C) 2007-2012  Brian Langenberger

#This program is free software; you can redistribute it and/or modify
#it under the terms of the GNU General Public License as published by
#the Free Software Foundation; either version 2 of the License, or
#(at your option) any later version.

#This program is distributed in the hope that it will be useful,
#but WITHOUT ANY WARRANTY; without even the implied warranty of
#MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#GNU General Public License for more details.

#You should have received a copy of the GNU General Public License
#along with this program; if not, write to the Free Software
#Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301  USA

import audiotools

class DiscID:
    def __init__(self, offsets, total_length, track_count):
        """offsets is a list of track offsets, in CD frames
        total_length is the total length of the disc, in CD frames
        track_count is the total number of tracks on the disc"""

        assert(len(offsets) == track_count)

        self.offsets = offsets
        self.total_length = total_length
        self.track_count = track_count

    def __repr__(self):
        return "DiscID(%s, %s, %s)" % \
            (repr(self.offsets),
             repr(self.total_length),
             repr(self.track_count))

    def __str__(self):
        def offset_seconds(i):
            assert(i >= 0)
            i /= 75
            seconds = 0
            while (i > 0):
                seconds += i % 10
                i /= 10
            return seconds

        return "%2.2X%4.4X%2.2X" % \
            (sum(map(offset_seconds, self.offsets)),
             self.total_length / 75,
             self.track_count)

def perform_lookup(offsets, total_length, track_count,
                   freedb_server, freedb_port):
    """performs a web-based lookup using
    a list of track offsets (in CD frames),
    total length of the disc (in CD frames),
    and track count
    on the given freedb_server string and freedb_int port

    iterates over a tuple of MetaData objects per track
    where the first result are all the MetaData matches
    for the first track, etc.  in the event there
    are multiple results for a given disc

    may raise urllib2.HTTPError if an error occurs querying the server
    or ValueError if the server returns invalid data
    """

    import re
    from socket import getfqdn
    from urllib2 import urlopen
    from urllib import urlencode
    from itertools import izip

    RESPONSE = re.compile(r'(\d{3}) (.+?)[\r\n]+')
    QUERY_RESULT = re.compile(r'(\S+) ([0-9a-fA-F]{8}) (.+)')
    FREEDB_LINE = re.compile(r'(\S+?)=(.+?)[\r\n]+')

    def parse_line(line):
        print repr(line)
        if (line.startswith(".")):
            return (None, line.rstrip("\r\n"))
        else:
            match = LINE.match(line)
            if (match is not None):
                return (int(match.group(1)), match.group(2))
            else:
                raise ValueError("invalid line")

    disc_id = DiscID(offsets, total_length, track_count)

    #perform initial FreeDB query
    #and get a list of category/disc id/title results
    #if any matches are found
    m = urlopen("http://%s:%d/~cddb/cddb.cgi" % (freedb_server, freedb_port),
                urlencode({"hello":"user %s %s %s" % \
                               (getfqdn(),
                                "audiotools",
                                audiotools.VERSION),
                           "proto":str(6),
                           "cmd":("cddb query %(disc_id)s %(track_count)d " +
                                  "%(offsets)s %(seconds)d") %
                           {"disc_id":disc_id,
                            "track_count":track_count,
                            "offsets":" ".join(map(str, offsets)),
                            "seconds":total_length / 75}}))

    response = RESPONSE.match(m.readline())
    if (response is None):
        raise ValueError("invalid response from server")
    else:
        #a list of (category, disc id, disc title) tuples
        matches = []
        code = int(response.group(1))
        if (code == 200):
            #single exact match
            match = QUERY_RESULT.match(response.group(2))
            if (match is not None):
                matches.append((match.group(1),
                                match.group(2),
                                match.group(3)))
            else:
                raise ValueError("invalid query result")
        elif ((code == 211) or (code == 210)):
            #multiple exact or inexact matches
            line = m.readline()
            while (not line.startswith(".")):
                match = QUERY_RESULT.match(line)
                if (match is not None):
                    matches.append((match.group(1),
                                    match.group(2),
                                    match.group(3)))
                else:
                    raise ValueError("invalid query result")
                line = m.readline()
        elif (code == 202):
            #no match found
            pass
        else:
            #some error has occurred
            raise ValueError(response.group(2))

    m.close()

    if (len(matches) > 0):
        freedb_files = []
        #for each result, query FreeDB for XMCD file data
        for (category, disc_id, title) in matches:
            m = urlopen("http://%s:%d/~cddb/cddb.cgi" % (freedb_server,
                                                         freedb_port),
                        urlencode({"hello":"user %s %s %s" % \
                                       (getfqdn(),
                                        "audiotools",
                                        audiotools.VERSION),
                                   "proto":str(6),
                                   "cmd":("cddb read %(category)s " +
                                          "%(disc_id)s") %
                                   {"category":category,
                                    "disc_id":disc_id}}))
            response = RESPONSE.match(m.readline())
            if (response is None):
                raise ValueError("invalid response from server")
            else:
                freedb = {}
                line = m.readline()
                while (not line.startswith(".")):
                    if (not line.startswith("#")):
                        entry = FREEDB_LINE.match(line)
                        if (entry is not None):
                            if (entry.group(1) in freedb):
                                freedb[entry.group(1)] += entry.group(2)
                            else:
                                freedb[entry.group(1)] = entry.group(2)
                    line = m.readline()
                freedb_files.append(freedb)

        #zip the XMCD files together by track
        #and yield a list of MetaData objects for each match per track
        for row in izip(*map(xmcd_metadata, freedb_files)):
            yield row
    else:
        #no matches found, so yield a group of empty tuples
        for i in xrange(track_count):
            yield tuple()

def xmcd_metadata(freedb_file):
    import re

    TTITLE = re.compile(r'TTITLE(\d+)')

    dtitle = freedb_file.get("DTITLE", "")
    if (" / " in dtitle):
        (album_artist, album_name) = dtitle.split(" / ", 1)
    else:
        album_artist = ""
        album_name = dtitle

    year = freedb_file.get("DYEAR", "")

    ttitles = [(int(m.group(1)), value) for (m, value) in
               [(TTITLE.match(key), value) for (key, value) in
                freedb_file.items()] if m is not None]

    if (len(ttitles) > 0):
        track_total = max([tracknum for (tracknum, ttitle) in ttitles]) + 1
    else:
        track_total = 0

    for (tracknum, ttitle) in sorted(ttitles,
                                     lambda x,y: cmp(x[0], y[0])):
        if (" / " in ttitle):
            (track_artist,
             track_name) = ttitle.split(" / ", 1)
        else:
            track_artist = album_artist
            track_name = ttitle

        yield audiotools.MetaData(
            track_name=track_name.decode('utf-8','replace'),
            track_number=tracknum + 1,
            track_total=track_total,
            album_name=album_name.decode('utf-8','replace'),
            artist_name=track_artist.decode('utf-8','replace'),
            year=year.decode('utf-8','replace'))