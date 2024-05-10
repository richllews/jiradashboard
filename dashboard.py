from imports import *
from constants import *

def get_issues_for_sprint(sprint_id):
    url = f"{JIRA_URL}/rest/agile/1.0/sprint/{sprint_id}/issue"
    response = requests.get(url, auth=(USER_EMAIL, API_TOKEN), headers=headers)
    response.raise_for_status()
    return response.json()

def get_issue_changelog(issue_id):
    url = f"{JIRA_URL}/rest/api/3/issue/{issue_id}?expand=changelog"
    response = requests.get(url, auth=(USER_EMAIL, API_TOKEN), headers=headers)
    response.raise_for_status()
    return response.json()['changelog']['histories']

def find_status_change_date(changelog, statuses, find_earliest=True):
    """Find the earliest or latest date when the issue was moved to specified statuses."""
    relevant_date = None
    search_order = changelog if find_earliest else reversed(changelog)
    for history in search_order:
        for item in history['items']:
            if item['field'] == 'status' and item['toString'] in statuses:
                date = datetime.strptime(history['created'], '%Y-%m-%dT%H:%M:%S.%f%z').replace(tzinfo=timezone.utc)
                if relevant_date is None or (find_earliest and date < relevant_date) or (not find_earliest and date > relevant_date):
                    relevant_date = date
    return relevant_date

from datetime import timedelta

def daterange(start_date, end_date):
    for n in range(int((end_date - start_date).days) + 1):
        yield start_date + timedelta(n)

def parse_issues(issue_data):
    issues = []
    final_statuses = ["Approved for Release", "Testing", "Closed"]
    active_statuses = ["In Progress", "Blocked", "Peer Review", "Pending Deployment"]
    status_timeline = {}

    for issue in issue_data['issues']:

        if issue['fields']['issuetype']['name'] in EXCLUDED_ISSUE_TYPES:
            continue 

        changelog = get_issue_changelog(issue['id'])
        previous_status = None

        # Tracking changes in active status for timeline
        for entry in sorted(changelog, key=lambda x: datetime.strptime(x['created'], '%Y-%m-%dT%H:%M:%S.%f%z').date()):
            for item in entry['items']:
                if item['field'] == 'status':
                    change_date = datetime.strptime(entry['created'], '%Y-%m-%dT%H:%M:%S.%f%z').date()
                    if item['fromString'] in active_statuses:
                        if change_date in status_timeline:
                            status_timeline[change_date] -= 1
                        else:
                            status_timeline[change_date] = status_timeline.get(change_date, 0) - 1
                    if item['toString'] in active_statuses:
                        if change_date in status_timeline:
                            status_timeline[change_date] += 1
                        else:
                            status_timeline[change_date] = status_timeline.get(change_date, 0) + 1

        # Finding dates related to status changes
        in_progress_date = find_status_change_date(changelog, ["In Progress"], find_earliest=True)
        last_final_status_date = find_status_change_date(changelog, final_statuses, find_earliest=False)

        # Calculating age of the ticket or setting it to 'N/A'
        if in_progress_date:
            end_date = last_final_status_date if last_final_status_date and last_final_status_date > in_progress_date else datetime.now(timezone.utc)
            age_seconds = (end_date - in_progress_date).total_seconds()
            age_days = age_seconds / 86400 + 1  # Convert seconds to days
        else:
            age_days = 'N/A'

        # Ensuring each issue has 'Date' key even if it's None
        issues.append({
            'Key': issue['key'],
            'Age (days)': age_days,
            'Status': issue['fields']['status']['name'],
            'Summary': issue['fields']['summary'],
            'Date': last_final_status_date.date() if last_final_status_date else None  # Ensure 'Date' is always set
        })

    if not status_timeline:
        return issues, {}

    # Normalize timeline to ensure all days are covered
    min_date = min(status_timeline.keys())
    max_date = max(status_timeline.keys())
    full_timeline = {}
    current_count = 0
    for single_date in daterange(min_date, max_date):
        if single_date in status_timeline:
            current_count += status_timeline[single_date]
        full_timeline[single_date] = max(0, current_count)

    return issues, full_timeline



def plot_data_and_save_html(issues, active_state_dates):
    df = pd.DataFrame(issues)
    df['Age (days)'] = pd.to_numeric(df['Age (days)'], errors='coerce')
    df['Age (days)'] = df['Age (days)'].round(1)
     # df['Age (days)'].fillna('Not Started', inplace=True)
    status_order = ["Ready For Dev", "Blocked", "In Progress", "Peer review", "Pending Deployment", "Testing", "Approved for Release", "Closed"]
    df['Status'] = pd.Categorical(df['Status'], categories=status_order, ordered=True)
    df.sort_values('Status', inplace=True)

    # Plotting ticket ages by status
    fig_scatter = go.Figure()
    fig_scatter.update_traces(hoverdistance=1450)  # Increase hover distance; adjust the value as needed
    urls = ['https://theplatform.jira.com/browse/' + key for key in df['Key']]
    for status in status_order:
        subset = df[df['Status'] == status]
        fig_scatter.add_trace(
            go.Scatter(
                x=[status] * len(subset),
                y=subset['Age (days)'],
                mode='markers',
                name='',
                marker=dict(size=12),
                text=subset['Key'] + ': ' + subset['Summary'],
                customdata=urls,
                hoverinfo='text+y',
                )
        )

    # Extract prefix from the 'Key' for pie chart grouping
    df['Prefix'] = df['Key'].apply(lambda x: x.split('-')[0])

    # Create the first general pie chart
    prefix_counts = df['Prefix'].value_counts().reset_index()
    prefix_counts.columns = ['Prefix', 'Count']
    fig_pie_general = go.Figure(data=[go.Pie(labels=prefix_counts['Prefix'], values=prefix_counts['Count'], hole=.3)])
    fig_pie_general.update_layout(title="Ticket Distribution by Project in the Current Sprint")

    # Filtering for final statuses
    final_statuses = ["Approved for Release", "Testing", "Closed"]
    final_df = df[df['Status'].isin(final_statuses)]

    # Create the second pie chart for tickets in final statuses
    final_prefix_counts = final_df['Prefix'].value_counts().reset_index()
    final_prefix_counts.columns = ['Prefix', 'Count']
    fig_pie_final = go.Figure(data=[go.Pie(labels=final_prefix_counts['Prefix'], values=final_prefix_counts['Count'], hole=.3)])
    fig_pie_final.update_layout(title="Completed Ticket Distribution by Project")

    # Create the second pie chart for ticket statuses
    pie_status_counts = df['Status'].value_counts().reset_index()
    pie_status_counts.columns = ['Status', 'Count']
    fig_pie_status = go.Figure(data=[go.Pie(labels=pie_status_counts['Status'], values=pie_status_counts['Count'], hole=.3)])
    fig_pie_status.update_layout(title="Tickets by Status")



    fig_scatter.update_layout(
        title='Item Ageing',
        xaxis_title='Status',
        yaxis_title='Age (days)',
        yaxis=dict(type='linear')
    )

    # Table of ticket details
    fig_table = go.Figure(data=[go.Table(
        header=dict(values=['Ticket Key', 'Summary','Age (days)', 'Status']),
        cells=dict(values=[df['Key'], df['Summary'], df['Age (days)'], df['Status']])
    )])
    fig_table.update_layout(title='Ticket Details')

    # Status summary table
    status_counts = df['Status'].value_counts().reindex(status_order, fill_value=0)
    fig_summary = go.Figure(data=[go.Table(
        header=dict(values=['Status', 'Count']),
        cells=dict(values=[status_counts.index, status_counts.values])
    )])
    fig_summary.update_layout(title='Status Summary')

    # New line plot for active items over time
    active_dates, counts = zip(*sorted(active_state_dates.items()))
    fig_active = go.Figure()
    fig_active.add_trace(go.Scatter(x=active_dates, y=counts, mode='lines+markers', name='Active Items Count'))
    fig_active.update_layout(title='WIP Trend', xaxis_title='Date', yaxis_title='Count')



    # Additional scatter plot for tickets in final statuses with Date on x-axis and Age on y-axis
    final_df = df[df['Status'].isin(["Approved for Release", "Testing", "Closed"])]

      #final_ticket_ids = final_df['Key'].tolist()
      #print("Final Status Ticket IDs in the scatter plot:", final_ticket_ids)


    fig_final_status_scatter = go.Figure()
    fig_final_status_scatter.add_trace(go.Scatter(
        x=final_df['Date'],
        y=final_df['Age (days)'],
        mode='markers',
        marker=dict(size=12),
        text=final_df['Key'],
        name=''
    ))

    # Adding percentile and average lines
    for percentile in [50, 70, 85]:
        value = np.percentile(final_df['Age (days)'].dropna(), percentile)
        fig_final_status_scatter.add_trace(go.Scatter(
            x=[final_df['Date'].min(), final_df['Date'].max()],
            y=[value, value],
            mode='lines',
            line=dict(dash='dash'),
            name=f'{percentile}th percentile'
        ))

    avg_age = final_df['Age (days)'].mean().round(1)
    fig_final_status_scatter.add_trace(go.Scatter(
        x=[final_df['Date'].min(), final_df['Date'].max()],
        y=[avg_age, avg_age],
        mode='lines',
        line=dict(color='red', width=1, dash='dash'),
        name='Average Age'
    ))

    fig_final_status_scatter.update_layout(
        title='Cycle Time',
        xaxis_title='Date',
        yaxis_title='Age (days)',
        legend_title="Legend"
    )

     # Table of cycle times
    fig_cycle = go.Figure(data=[go.Table(
        header=dict(values=['Average','85th']),
        cells=dict(values=[avg_age,value])
    )])
    fig_cycle.update_layout(title='Cycle Time Stats')

    # Saving to HTML
    scatter_html = pio.to_html(fig_scatter, full_html=False)
    table_html = pio.to_html(fig_table, full_html=False)
    summary_html = pio.to_html(fig_summary, full_html=False)
    active_html = pio.to_html(fig_active, full_html=False)
    final_html = pio.to_html(fig_final_status_scatter, full_html=False)
    pie_html_general = pio.to_html(fig_pie_general, full_html=False)
    pie_html_final = pio.to_html(fig_pie_final, full_html=False)
    cycle_html_final = pio.to_html(fig_cycle, full_html=False)
    pie_html_status = pio.to_html(fig_pie_status, full_html=False)
    html = f"""
    <html>
    <head>
    <title>Dashboard</title>
    </head>
    <body>
    <h1>JIRA Ticket Analysis Dashboard</h1>
    {scatter_html}
    {table_html}   
    {active_html}
    {final_html}
    {cycle_html_final}
    {summary_html}
    {pie_html_general}
    {pie_html_final}   
    {pie_html_status}   
    </body>
    </html>
    """

    with open('Sprint_test' + sprint_id + '.html', 'w') as f:
        f.write(html)
        print('Sprint_test' + sprint_id + '.html' + ' created')

        

def main(sprint_id):
    issue_data = get_issues_for_sprint(sprint_id)
    issues, active_state_dates = parse_issues(issue_data)
    plot_data_and_save_html(issues, active_state_dates)


if __name__ == '__main__':
    sprint_id = input("Enter Sprint ID: ")

    main(sprint_id)
