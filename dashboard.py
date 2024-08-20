from imports import *
from constants import *

# Utility functions
def get_active_sprint_id(board_id):
    url = f"{JIRA_URL}/rest/agile/1.0/board/{board_id}/sprint?state=active"
    try:
        response = requests.get(url, auth=(USER_EMAIL, API_TOKEN), headers=headers)
        response.raise_for_status()
        sprints = response.json()['values']
        if sprints:
            return sprints[0]['id']  # Assuming there's only one active sprint
        else:
            print(f"No active sprint found for board {board_id}.")
            return None
    except requests.exceptions.RequestException as e:
        print(f"Error fetching active sprint for board {board_id}: {e}")
        return None

def get_issues_for_sprint(sprint_id):
    url = f"{JIRA_URL}/rest/agile/1.0/sprint/{sprint_id}/issue"
    try:
        response = requests.get(url, auth=(USER_EMAIL, API_TOKEN), headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching issues for sprint {sprint_id}: {e}")
        return None

def get_issue_changelog(issue_id):
    url = f"{JIRA_URL}/rest/api/3/issue/{issue_id}?expand=changelog"
    try:
        response = requests.get(url, auth=(USER_EMAIL, API_TOKEN), headers=headers)
        response.raise_for_status()
        return response.json()['changelog']['histories']
    except requests.exceptions.RequestException as e:
        print(f"Error fetching changelog for issue {issue_id}: {e}")
        return []

def find_status_change_date(changelog, statuses, find_earliest=True):
    relevant_date = None
    search_order = changelog if find_earliest else reversed(changelog)
    for history in search_order:
        for item in history['items']:
            if item['field'] == 'status' and item['toString'].title() in statuses:
                date = datetime.strptime(history['created'], '%Y-%m-%dT%H:%M:%S.%f%z').replace(tzinfo=timezone.utc)
                if relevant_date is None or (find_earliest and date < relevant_date) or (not find_earliest and date > relevant_date):
                    relevant_date = date
    return relevant_date

def calculate_time_in_status(changelog):
    time_in_status = {}
    current_status = None
    current_start_date = None
    
    for history in sorted(changelog, key=lambda x: datetime.strptime(x['created'], '%Y-%m-%dT%H:%M:%S.%f%z')):
        for item in history['items']:
            if item['field'] == 'status':
                change_date = datetime.strptime(history['created'], '%Y-%m-%dT%H:%M:%S.%f%z')
                if current_status is not None:
                    duration = (change_date - current_start_date).total_seconds() / 86400  # Convert to days
                    if current_status in time_in_status:
                        time_in_status[current_status] += duration
                    else:
                        time_in_status[current_status] = duration
                current_status = item['toString'].title()
                current_start_date = change_date

    if current_status is not None and current_start_date is not None:
        duration = (datetime.now(timezone.utc) - current_start_date).total_seconds() / 86400
        if current_status in time_in_status:
            time_in_status[current_status] += duration
        else:
            time_in_status[current_status] = duration
    
    return time_in_status

def daterange(start_date, end_date):
    for n in range(int((end_date - start_date).days) + 1):
        yield start_date + timedelta(n)

def parse_issues(issue_data):
    issues = []
    final_statuses = ["Approved For Release", "Testing", "Closed"]
    active_statuses = ["In Progress", "Blocked", "Peer Review", "Pending Deployment"]
    status_timeline = {}
    time_in_status_all_issues = {}
    current_status_times = []
    cycle_times = []
    active_tickets_by_date = {}

    for issue in issue_data['issues']:
        issue_type = issue['fields']['issuetype']['name']
        changelog = get_issue_changelog(issue['id'])

        time_in_status = calculate_time_in_status(changelog)
        time_in_status_all_issues[issue['key']] = time_in_status

        current_status = issue['fields']['status']['name'].title()
        if current_status == "Backlog":
            continue  # Skip issues in "Backlog" status

        if current_status in time_in_status:
            current_status_times.append({
                'Key': issue['key'],
                'Status': current_status,
                'Time in Status (days)': time_in_status[current_status]
            })
        
        in_active_status = False

        for entry in sorted(changelog, key=lambda x: datetime.strptime(x['created'], '%Y-%m-%dT%H:%M:%S.%f%z').date()):
            change_date = datetime.strptime(entry['created'], '%Y-%m-%dT%H:%M:%S.%f%z').date()
            for item in entry['items']:
                if item['field'] == 'status':
                    from_status = item.get('fromString')
                    to_status = item.get('toString')
                    if from_status:
                        from_status = from_status.title()
                    if to_status:
                        to_status = to_status.title()

                    if to_status in active_statuses and from_status not in active_statuses:
                        status_timeline[change_date] = status_timeline.get(change_date, 0) + 1
                        active_tickets_by_date.setdefault(change_date, []).append(issue['key'])
                    elif from_status in active_statuses and to_status not in active_statuses:
                        status_timeline[change_date] = status_timeline.get(change_date, 0) - 1
                        if issue['key'] in active_tickets_by_date.get(change_date, []):
                            active_tickets_by_date[change_date].remove(issue['key'])

        in_progress_date = find_status_change_date(changelog, ["In Progress"], find_earliest=True)
        last_final_status_date = find_status_change_date(changelog, final_statuses, find_earliest=False)

        if in_progress_date:
            end_date = last_final_status_date if last_final_status_date and last_final_status_date > in_progress_date else datetime.now(timezone.utc)
            age_seconds = (end_date - in_progress_date).total_seconds()
            age_days = age_seconds / 86400 + 1
        else:
            age_days = 'N/A'

        if issue_type not in EXCLUDED_ISSUE_TYPES and in_progress_date and last_final_status_date and last_final_status_date > in_progress_date:
            cycle_time_seconds = (last_final_status_date - in_progress_date).total_seconds()
            cycle_time_days = cycle_time_seconds / 86400 + 1
            cycle_times.append({'key': issue['key'], 'cycle_time': cycle_time_days, 'date': last_final_status_date.date()})
        else:
            cycle_time_days = None

        issues.append({
            'Key': issue['key'],
            'Age (days)': age_days,
            'Cycle Time (days)': cycle_time_days,
            'Status': issue['fields']['status']['name'].title(),
            'Summary': issue['fields']['summary'],
            'issuetype': issue['fields']['issuetype']['name'],
            'Date': last_final_status_date.date() if last_final_status_date else None
        })

    if status_timeline:
        min_date = min(status_timeline.keys())
        max_date = max(status_timeline.keys())
        full_timeline = {}
        current_count = 0
        for single_date in daterange(min_date, max_date):
            if single_date in status_timeline:
                current_count += status_timeline[single_date]
            full_timeline[single_date] = max(0, current_count)

        for date, tickets in active_tickets_by_date.items():
            print(f"DEBUG: Date: {date}, Tickets: {tickets}, Count: {len(tickets)}")

        return issues, full_timeline, time_in_status_all_issues, current_status_times, cycle_times, active_tickets_by_date
    else:
        return issues, {}, time_in_status_all_issues, current_status_times, cycle_times, active_tickets_by_date



def plot_wip_trend(active_state_dates, active_tickets_by_date):
    if active_state_dates:
        active_dates, counts = zip(*sorted(active_state_dates.items()))

        # Detailed logging to debug the issue
        #print("DEBUG: WIP Trend - Active Tickets by Date")
        for date in active_dates:
            tickets_on_date = active_tickets_by_date.get(date, [])
            #print(f"Date: {date}, Graph Count: {counts[active_dates.index(date)]}, Hover Tickets: {tickets_on_date}, Hover Count: {len(tickets_on_date)}")
        
        fig_active = go.Figure()
        fig_active.add_trace(go.Scatter(
            x=active_dates, 
            y=counts, 
            mode='lines+markers', 
            name='Active Items Count',
            text=[f"{date}: {', '.join(active_tickets_by_date.get(date, []))}" for date in active_dates], 
            hoverinfo='text'
        ))
        fig_active.update_layout(title='WIP Trend', xaxis_title='Date', yaxis_title='Count')
        return pio.to_html(fig_active, full_html=False)
    return ""





def plot_data_and_save_html(issues, active_state_dates, time_in_status_all_issues, current_status_times, cycle_times, sprint_id, active_tickets_by_date):
    df = pd.DataFrame(issues)
    df['Age (days)'] = pd.to_numeric(df['Age (days)'], errors='coerce').round(1)
    status_order = ["Ready For Dev", "Blocked", "In Progress", "Peer Review", "Pending Deployment", "Testing", "Approved For Release", "Closed"]
    df['Status'] = pd.Categorical(df['Status'], categories=status_order, ordered=True)
    df.sort_values('Status', inplace=True)

    # Plotting ticket ages by status
    fig_scatter = go.Figure()
    fig_scatter.update_traces(hoverdistance=1450)
    urls = ['https://theplatform.jira.com/browse/' + key for key in df['Key']]
    for status in status_order:
        subset = df[df['Status'] == status]
        fig_scatter.add_trace(go.Scatter(
            x=[status] * len(subset),
            y=subset['Age (days)'],
            mode='markers',
            name=status,
            marker=dict(size=12),
            text=subset['Key'] + ': ' + subset['Summary'],
            customdata=urls,
            hoverinfo='text+y',
        ))

    df['Prefix'] = df['Key'].apply(lambda x: x.split('-')[0])
    prefix_counts = df['Prefix'].value_counts().reset_index()
    prefix_counts.columns = ['Prefix', 'Count']
    fig_pie_general = go.Figure(data=[go.Pie(labels=prefix_counts['Prefix'], values=prefix_counts['Count'], hole=.3)])
    fig_pie_general.update_layout(title="Ticket Distribution by Project in the Current Sprint")

    final_statuses = ["Approved For Release", "Testing", "Closed"]
    final_df = df[df['Status'].isin(final_statuses)]
    filtered_df = final_df[final_df['issuetype'] != 'Sub-task']

    final_prefix_counts = filtered_df['Prefix'].value_counts().reset_index()
    final_prefix_counts.columns = ['Prefix', 'Count']
    fig_pie_final = go.Figure(data=[go.Pie(labels=final_prefix_counts['Prefix'], values=final_prefix_counts['Count'], hole=.3)])
    fig_pie_final.update_layout(title="Completed Ticket Distribution by Project")

    pie_status_counts = df['Status'].value_counts().reset_index()
    pie_status_counts.columns = ['Status', 'Count']
    fig_pie_status = go.Figure(data=[go.Pie(labels=pie_status_counts['Status'], values=pie_status_counts['Count'], hole=.3)])
    fig_pie_status.update_layout(title="Tickets by Status")

    fig_scatter.update_layout(title='Item Ageing', xaxis_title='Status', yaxis_title='Age (days)', yaxis=dict(type='linear'))

    fig_table = go.Figure(data=[go.Table(
        header=dict(values=['Ticket Key', 'Issue type', 'Summary','Age (days)', 'Status']),
        cells=dict(values=[df['Key'], df['issuetype'], df['Summary'], df['Age (days)'], df['Status']])
    )])
    fig_table.update_layout(title='Ticket Details')

    status_counts = df['Status'].value_counts().reindex(status_order, fill_value=0)
    fig_summary = go.Figure(data=[go.Table(
        header=dict(values=['Status', 'Count']),
        cells=dict(values=[status_counts.index, status_counts.values])
    )])
    fig_summary.update_layout(title='Status Summary', width=600, height=500)

    # Cycle Time Plot
    fig_final_status_scatter = go.Figure()
    if cycle_times:
        cycle_df = pd.DataFrame(cycle_times)
        avg_cycle_time = cycle_df['cycle_time'].mean().round(1)
        percentiles = [50, 70, 85]
        percentile_values = {percentile: np.percentile(cycle_df['cycle_time'], percentile) for percentile in percentiles}

        for percentile, value in percentile_values.items():
            fig_final_status_scatter.add_trace(go.Scatter(
                x=[cycle_df['date'].min(), cycle_df['date'].max()],
                y=[value, value],
                mode='lines',
                line=dict(dash='dash'),
                name=f'{percentile}th percentile'
            ))

        fig_final_status_scatter.add_trace(go.Scatter(
            x=cycle_df['date'],
            y=cycle_df['cycle_time'],
            mode='markers',
            marker=dict(size=12, color='blue'),
            name='Cycle Time'
        ))

        fig_final_status_scatter.add_trace(go.Scatter(
            x=[cycle_df['date'].min(), cycle_df['date'].max()],
            y=[avg_cycle_time, avg_cycle_time],
            mode='lines',
            line=dict(color='red', width=1, dash='dash'),
            name='Average Cycle Time'
        ))

    fig_final_status_scatter.update_layout(title='Cycle Time', xaxis_title='Date', yaxis_title='Cycle Time (days)', legend_title="Legend")

    time_in_status_df = pd.DataFrame(time_in_status_all_issues).T.fillna(0)
    fig_time_in_status = go.Figure()
    for status in time_in_status_df.columns:
        fig_time_in_status.add_trace(go.Bar(
            x=time_in_status_df.index,
            y=time_in_status_df[status],
            name=status
        ))

    fig_time_in_status.update_layout(title='Time Spent in Each Status (life of ticket)', xaxis_title='Ticket Key', yaxis_title='Time (days)', barmode='stack')

    current_status_df = pd.DataFrame(current_status_times)
    fig_current_status_scatter = go.Figure()
    for status in status_order:
        subset = current_status_df[current_status_df['Status'] == status]
        fig_current_status_scatter.add_trace(go.Scatter(
            x=[status] * len(subset),
            y=subset['Time in Status (days)'],
            mode='markers',
            marker=dict(size=12),
            text=subset['Key'],
            name=status
        ))

    fig_current_status_scatter.update_layout(title='How long have tickets been in a column?', xaxis_title='Status', yaxis_title='Time in Status (days)', legend_title="Legend")

    fig_cycle = go.Figure()
    if cycle_times:
        fig_cycle = go.Figure(data=[go.Table(
            header=dict(values=['Average Cycle Time','85th Percentile']),
            cells=dict(values=[avg_cycle_time, percentile_values[85]])
        )])
        fig_cycle.update_layout(title='Cycle Time Stats', width=500, height=300)

    scatter_html = pio.to_html(fig_scatter, full_html=False)
    table_html = pio.to_html(fig_table, full_html=False)
    summary_html = pio.to_html(fig_summary, full_html=False)
    final_html = pio.to_html(fig_final_status_scatter, full_html=False)
    pie_html_general = pio.to_html(fig_pie_general, full_html=False)
    pie_html_final = pio.to_html(fig_pie_final, full_html=False)
    cycle_html_final = pio.to_html(fig_cycle, full_html=False)
    pie_html_status = pio.to_html(fig_pie_status, full_html=False)
    time_in_status_html = pio.to_html(fig_time_in_status, full_html=False)
    current_status_scatter_html = pio.to_html(fig_current_status_scatter, full_html=False)
    
    wip_trend_html = plot_wip_trend(active_state_dates, active_tickets_by_date)

    html = f"""
    <html>
    <head>
    <title>Dashboard</title>
    </head>
    <body>
    <h1>Sprint Dashboard</h1>
    {scatter_html}
    {time_in_status_html}
    {current_status_scatter_html}
    {table_html}
    {wip_trend_html}
    {final_html}
    {cycle_html_final}
    {summary_html}
    {pie_html_general}
    {pie_html_final}
    {pie_html_status}   
    </body>
    </html>
    """

    file_path = f'Sprint_{sprint_id}.html'
    with open(file_path, 'w') as f:
        f.write(html)
    print(f'{file_path} created')

def main(board_id):
    sprint_id = get_active_sprint_id(board_id)
    if sprint_id:
        issue_data = get_issues_for_sprint(sprint_id)
        if issue_data:
            issues, active_state_dates, time_in_status_all_issues, current_status_times, cycle_times, active_tickets_by_date = parse_issues(issue_data)
            plot_data_and_save_html(issues, active_state_dates, time_in_status_all_issues, current_status_times, cycle_times, sprint_id, active_tickets_by_date)
        else:
            print(f"Failed to retrieve data for sprint {sprint_id}")
    else:
        print(f"Failed to retrieve an active sprint for board {board_id}")

if __name__ == '__main__':
    board_id = input("Enter Board ID: ")
    main(board_id)

