from __future__ import print_function
import requests
import pandas as pd
from bs4 import BeautifulSoup
import httplib2
import os
import sys

from apiclient import discovery
import oauth2client
from oauth2client import client
from oauth2client import tools

try:
    import argparse
    flags = argparse.ArgumentParser(parents=[tools.argparser]).parse_args()
except ImportError:
    flags = None


cal_id = 'murj9blvn8bq5sc33khkh568d8@group.calendar.google.com'
tz = '-05:00'  # Toronto timezone

SCOPES = 'https://www.googleapis.com/auth/calendar'
CLIENT_SECRET_FILE = 'client_secret.json'
APPLICATION_NAME = 'EconSeminars'


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
    out['title'] = elem[4].text.strip()
    out['location'] = elem[5].text.strip()
    out['organizer'] = ' '.join(elem[6].text.split()[1:])
    return out


def delete_event(cal, row):
    """
    Deletes an event from the calendar.
    args:
        cal - the API handler
        row - a dictionary-like object containing the key date, time, and location
    """
    start = pd.to_datetime(
        row['date'] + ' ' + row['time'].split('-')[0]).isoformat() + tz
    end = pd.to_datetime(
        row['date'] + ' ' + row['time'].split('-')[1]).isoformat() + tz
    eventsResult = cal.events().list(
        calendarId=cal_id, timeMin=end, timeMax=start, maxResults=10, singleEvents=True,
        orderBy='startTime').execute()

    events = eventsResult.get('items', [])

    for event in events:
        if event['location'] == row['location']:
            cal.events().delete(calendarId=cal_id, eventId=event['id']).execute()


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
                .split('-')[0]).isoformat() + tz,
        },
        'end': {
            'dateTime': pd.to_datetime(row['date'] + ' ' + row['time']
                .split('-')[1]).isoformat() + tz,
        },
    }
    cal.events().insert(calendarId=cal_id, body=body).execute()


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
    url = 'https://www.economics.utoronto.ca/index.php/index/research/seminars?dateRange=2015&seriesId=0'
    r = requests.get(url)
    soup = BeautifulSoup(r.text, 'lxml')
    seminars = soup.find_all('table', 'people')
    data = [parse_seminar(sem) for sem in seminars]

    # The new dataset
    df = pd.DataFrame(data)
    df['time'] = df['time'].str.replace(u'\u2013', '-')

    # The old dataset
    try:
        old_seminars = pd.read_csv('seminars.csv', encoding='utf8')
    except IOError:
        print('File seminars.csv does not exist. Will add all seminars.')
        ask_yn()
        old_seminars = pd.DataFrame(columns=df.columns)

    # We compare the two dataset. If an entry as changed, was added, or was deleted,
    # it will be included in to_remove and/or to_add.
    diff = pd.merge(df, old_seminars, on=list(df.columns), how='outer', indicator=True)
    to_remove = diff[diff['_merge'] == 'right_only']
    to_add = diff[diff['_merge'] == 'left_only']

    # If there are changes, do them.
    if (len(to_remove) != 0) or (len(to_add) != 0):
        credentials = get_credentials()
        http = credentials.authorize(httplib2.Http())
        cal = discovery.build('calendar', 'v3', http=http)

        print('Deleting {} seminars'.format(len(to_remove)))
        for key, row in to_remove.iterrows():
            delete_event(cal, row)

        print('Adding {} seminars'.format(len(to_add)))
        for key, row in to_add.iterrows():
            add_event(cal, row)

        df.to_csv('seminars.csv', encoding='utf-8', index=False)
