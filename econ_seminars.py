from __future__ import print_function
import requests
import pandas as pd
from bs4 import BeautifulSoup
import httplib2
import os
import sys
import time

from apiclient import discovery
import oauth2client
from oauth2client import client
from oauth2client import tools
from oauth2client.service_account import ServiceAccountCredentials

try:
    import argparse
    flags = argparse.ArgumentParser(parents=[tools.argparser]).parse_args()
except ImportError:
    flags = None

os.chdir('/home/pi/EconSeminars')

cal_id = 'murj9blvn8bq5sc33khkh568d8@group.calendar.google.com'
tz = 'Canada/Eastern'  # Toronto timezone
tz0 = '-04:00'
tz1 = '-05:00'

SCOPES = 'https://www.googleapis.com/auth/calendar'
CLIENT_SECRET_FILE = 'client_secret.json'
APPLICATION_NAME = 'EconSeminars'


def get_credentials_sa():
    return ServiceAccountCredentials.from_json_keyfile_name(
        'gspread-0e66a6d8d261.json', scopes=SCOPES)


def get_credentials():
    """Gets valid user credentials from storage.

    If nothing has been stored, or if the stored credentials are invalid,
    the OAuth2 flow is completed to obtain the new credentials.

    Returns:
        Credentials, the obtained credential.
    """
    home_dir = os.path.expanduser('~')
    credential_dir = os.path.join(home_dir, '.credentials')
    if not os.path.exists(credential_dir):
        os.makedirs(credential_dir)
    credential_path = os.path.join(credential_dir, 'econ_seminars.json')

    store = oauth2client.file.Storage(credential_path)
    credentials = store.get()
    if not credentials or credentials.invalid:
        flow = client.flow_from_clientsecrets(CLIENT_SECRET_FILE, SCOPES)
        flow.user_agent = APPLICATION_NAME
        credentials = tools.run_flow(flow, store, flags)
        print('Storing credentials to ' + credential_path)
    return credentials


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
    }
    response = cal.events().insert(calendarId=cal_id, body=body).execute()
    time.sleep(0.5)
    return response


def ask_yn():
        response = raw_input('Is this what you want? [y]/n : ')
        if (response == 'y') or (response == ''):
            return
        elif response == 'n':
            sys.exit()
        else:
            ask_yn()


if __name__ == '__main__':
    # Getting the new data by scraping the webpage
    url = 'https://www.economics.utoronto.ca/index.php/index/research/seminars?dateRange=2016&seriesId=0'
    # url = 'https://www.economics.utoronto.ca/index.php/index/research/seminars?dateRange=thisWeek&seriesId=0'
    r = requests.get(url)
    soup = BeautifulSoup(r.text, 'lxml')
    seminars = soup.find_all('table', 'people')
    data = [parse_seminar(sem) for sem in seminars]

    # The new dataset
    df = pd.DataFrame(data)
    df['time'] = df['time'].str.replace(u'\u2013', '-')

    # The old dataset
    try:
        old_seminars = pd.read_pickle('seminars.pkl')
    except IOError:
        print('File seminars.csv does not exist. Will add all seminars.')
        ask_yn()
        old_seminars = pd.DataFrame(columns=df.columns)

    # We compare the two dataset. If an entry as changed, was added, or was deleted,
    # it will be included in to_remove and/or to_add.
    diff = pd.merge(df, old_seminars, on=list(df.columns), how='outer', indicator=True)
    to_remove = diff[diff['_merge'] == 'right_only']
    to_add = diff[diff['_merge'] == 'left_only']

    # Add IDs to the new dataset.

    # If there are changes, do them.
    credentials = get_credentials_sa()
    http = credentials.authorize(httplib2.Http())
    cal = discovery.build('calendar', 'v3', http=http)
    if (len(to_remove) != 0) or (len(to_add) != 0):

        print('Deleting {} seminars'.format(len(to_remove)))
        for key, row in to_remove.iterrows():
            print(u'{} - {}'.format(row['date'], row['presenter']))
            delete_event(cal, row)

        print('Adding {} seminars'.format(len(to_add)))
        for key, row in to_add.iterrows():
            print(u'{} - {}'.format(row['date'], row['presenter']))
            response = add_event(cal, row)
            diff.ix[key, 'id'] = response['id']

        new_df = diff[diff['_merge'] != 'right_only'].drop('_merge', axis=1)

        new_df.to_pickle('seminars.pkl')
	
	print('Done!')
