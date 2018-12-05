"""

TODO:
- Create my own ID system
- Transparent
- Status Cancelled
- source.url (url to paper) - impossible
"""

from __future__ import print_function
import requests
import pandas as pd
from bs4 import BeautifulSoup
import httplib2
import os
import sys
import time

from apiclient import discovery
from oauth2client.service_account import ServiceAccountCredentials

path = os.path.dirname(sys.argv[0])
if path == '':
    path = '.'
os.chdir(path)

cal_id = 'murj9blvn8bq5sc33khkh568d8@group.calendar.google.com'
# cal_id = 'lo63qeln25u2niq0eog0v2uvs0@group.calendar.google.com'
tz = 'Canada/Eastern'  # Toronto timezone

SCOPES = 'https://www.googleapis.com/auth/calendar'
CLIENT_SECRET_FILE = 'client_secret.json'
APPLICATION_NAME = 'EconSeminars'


def ask_yn():
    response = raw_input('Is this what you want? [y]/n : ')
    if (response == 'y') or (response == ''):
        return
    elif response == 'n':
        sys.exit()
    else:
        ask_yn()


def get_credentials_sa():
    return ServiceAccountCredentials.from_json_keyfile_name(
        'gspread-0e66a6d8d261.json', scopes=SCOPES)


def parse_seminar(seminar_html):
    """
    Parse a BeautifulSoup object representing a table (a seminar)
    """
    elem = seminar_html.find_all('td')
    out = dict()
    out['date'] = elem[0].text.strip()
    out['time'] = elem[1].text.strip()
    out['field'] = elem[2].text.strip()
    out['presenter'] = elem[3].text.strip()
    if 'Cancelled' in out['presenter']:
        out['presenter'] = 'CANCELLED - ' + out['presenter']
    out['title'] = elem[4].text.strip()
    out['location'] = elem[-3].text.strip()
    out['organizer'] = ' '.join(elem[-2].text.split()[1:])
    return out


def get_seminars():
    # Getting the new data by scraping the webpage
    url = 'https://www.economics.utoronto.ca/index.php/index/research/seminars'

    payload = {'dateRange': 'all', 'seriesId': 0}

    r = requests.get(url, params=payload)
    soup = BeautifulSoup(r.text, 'lxml')
    seminars = soup.find_all('table', 'people')
    data = [parse_seminar(sem) for sem in seminars]

    # The new dataset
    df = pd.DataFrame(data)
    df['time'] = df['time'].str.replace(u'\u2013', '-')

    datestr1 = df['date'] + ' ' + df['time'].str.split('-').str[0]
    datestr2 = df['date'] + ' ' + df['time'].str.split('-').str[1]
    df['start'] = pd.to_datetime(datestr1)
    df['end'] = pd.to_datetime(datestr2)
    df['starttime'] = df.start.map(lambda x: x.isoformat())
    df['endtime'] = df.end.map(lambda x: x.isoformat())

    return df[df.start.dt.year >= 2016]


def delete_event(cal, row):
    """
    Deletes an event from the calendar.
    args:
        cal - the API handler
        row - a dictionary-like object containing the key date, time, and location
    """
    cal.events().delete(calendarId=cal_id, eventId=row['id']).execute()


def delete_all(cal):
    """
    Deletes an event from the calendar.
    args:
        cal - the API handler
        row - a dictionary-like object containing the key date, time, and location
    """
    page_token = None
    while True:
        eventsResult = cal.events().list(
            calendarId=cal_id, pageToken=page_token, maxResults=50).execute()
        events = eventsResult.get('items', [])

        for event in events:
            print(event['summary'])
            cal.events().delete(calendarId=cal_id, eventId=event['id']).execute()
            time.sleep(0.5)

        page_token = eventsResult.get('nextPageToken')
        if not page_token:
            break


def get_all_events(cal):
    list_events = []
    page_token = None
    while True:
        eventsResult = cal.events().list(
            calendarId=cal_id, pageToken=page_token, maxResults=50).execute()
        events = eventsResult.get('items', [])

        for event in events:
            list_events.append(event)

        page_token = eventsResult.get('nextPageToken')
        if not page_token:
            break

    return list_events


def add_event(cal, row):
    """
    Inserts an event in the calendar.
    args:
        cal - the API handler
        row - a dictionary-like object containing the key date, time, location,
            field, presenter, and title
    """
    body = {
        'summary': row['presenter'] + ' - ' + row['field'],
        'location': row['location'],
        'description': row['title'],
        'start': {
            'dateTime': pd.to_datetime(row['date'] + ' ' + row['time']
                                       .split('-')[0]).isoformat(),
            'timeZone': tz
        },
        'end': {
            'dateTime': pd.to_datetime(row['date'] + ' ' + row['time']
                                       .split('-')[1]).isoformat(),
            'timeZone': tz
        },
        'transparency': 'transparent',
    }
    response = cal.events().insert(calendarId=cal_id, body=body).execute()
    time.sleep(0.5)
    return response


if __name__ == '__main__':

    df = get_seminars()

    # If there are changes, do them.
    credentials = get_credentials_sa()
    http = credentials.authorize(httplib2.Http())
    cal = discovery.build('calendar', 'v3', http=http)

    cal_events_pre = pd.DataFrame(get_all_events(cal))

    cal_events = pd.DataFrame()
    cal_events['title'] = cal_events_pre['description']
    cal_events['start'] = cal_events_pre.start.map(lambda x: x['dateTime'])
    cal_events['end'] = cal_events_pre.end.map(lambda x: x['dateTime'])
    cal_events['presenter'] = cal_events_pre.summary.str.rsplit(' - ', 1).str[0]
    cal_events['field'] = cal_events_pre.summary.str.rsplit(' - ', 1).str[1]
    cal_events['location'] = cal_events_pre.location

    cal_events['starttime'] = cal_events.start.str[:19]
    cal_events['endtime'] = cal_events.end.str[:19]
    cal_events['id'] = cal_events_pre.id

    cols = ['title', 'starttime', 'endtime', 'field', 'presenter', 'location']

    # We compare the two dataset. If an entry as changed, was added, or was deleted,
    # it will be included in to_remove and/or to_add.
    diff = pd.merge(df, cal_events, on=cols, how='outer', indicator=True)
    to_remove = diff[diff['_merge'] == 'right_only']
    to_add = diff[diff['_merge'] == 'left_only']

    if (len(to_remove) != 0) or (len(to_add) != 0):
        print('Deleting {} seminars'.format(len(to_remove)))
        for key, row in to_remove.iterrows():
            delete_event(cal, row)
        print('Adding {} seminars'.format(len(to_add)))
        for key, row in to_add.iterrows():
            add_event(cal, row)
    print('Done!')
