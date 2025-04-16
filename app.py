import dash
from dash import dcc, html, callback_context
from dash.dependencies import Input, Output, State, ALL
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import dash_leaflet as dl
from datetime import datetime, timezone, timedelta
import requests
import json
import random
import time
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ------------------------------------
# 1. Data Loading & Preprocessing
# ------------------------------------
# Use absolute paths for data files
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
locations_df = pd.read_csv(os.path.join(BASE_DIR, 'locations.csv'))

# Load sensor parameters data
with open(os.path.join(BASE_DIR, "all_sensors_data.json"), "r") as f:
    sensor_parameters_data = json.load(f)

# Build the API keys list from environment variables
api_keys = []
for i in range(1, 12):
    key = os.getenv(f'OPENAQ_API_KEY_{i}')
    if key:
        api_keys.append(key)

# Create a dictionary for quick lookup by sensor_id
sensor_parameters = {}
for location in sensor_parameters_data:
    for sensor in location['sensors']:
        sensor_parameters[sensor['sensorid']] = {
            'parameter_name': sensor['parameter_name'],
            'units': sensor['units'],
            'display_name': sensor['display_name']
        }

# Parameter mapping for display
parameter_mapping = {
    'pm25': 'PM2.5',
    'pm10': 'PM10',
    'no2': 'NO2',
    'co': 'CO',
    'so2': 'SO2',
    'o3': 'O3',
    'rh': 'Relative Humidity'
}

# ------------------------------------
# 2. AQI Calculation
# ------------------------------------
def calculate_aqi_subindex(value, parameter):
    breakpoints = {
        "PM2.5": [
            (0.0, 12.0, 0, 50),
            (12.1, 35.4, 51, 100),
            (35.5, 55.4, 101, 150),
            (55.5, 150.4, 151, 200),
            (150.5, 250.4, 201, 300),
            (250.5, 350.4, 301, 400),
            (350.5, 500.4, 401, 500)
        ],
        "PM10": [
            (0, 54, 0, 50),
            (55, 154, 51, 100),
            (155, 254, 101, 150),
            (255, 354, 151, 200),
            (355, 424, 201, 300),
            (425, 504, 301, 400),
            (505, 604, 401, 500)
        ],
        "CO": [
            (0.0, 4.4, 0, 50),
            (4.5, 9.4, 51, 100),
            (9.5, 12.4, 101, 150),
            (12.5, 15.4, 151, 200),
            (15.5, 30.4, 201, 300),
            (30.5, 40.4, 301, 400),
            (40.5, 50.4, 401, 500)
        ],
        "O3": [
            (0, 54, 0, 50),
            (55, 70, 51, 100),
            (71, 85, 101, 150),
            (86, 105, 151, 200),
            (106, 200, 201, 300)
        ],
        "NO2": [
            (0, 53, 0, 50),
            (54, 100, 51, 100),
            (101, 360, 101, 150),
            (361, 649, 151, 200),
            (650, 1249, 201, 300),
            (1250, 1649, 301, 400),
            (1650, 2049, 401, 500)
        ],
        "SO2": [
            (0, 35, 0, 50),
            (36, 75, 51, 100),
            (76, 185, 101, 150),
            (186, 304, 151, 200),
            (305, 604, 201, 300),
            (605, 804, 301, 400),
            (805, 1004, 401, 500)
        ]
    }
    
    if parameter == "CO":
        value = value / 1000.0
    if parameter == "O3":
        value = value / 2.0

    if parameter not in breakpoints:
        return 0

    for i, (Clow, Chigh, Ilow, Ihigh) in enumerate(breakpoints[parameter]):
        if i == len(breakpoints[parameter]) - 1:
            if Clow <= value <= Chigh:
                subindex = ((Ihigh - Ilow) / (Chigh - Clow)) * (value - Clow) + Ilow
                return round(subindex)
        else:
            if Clow <= value < Chigh:
                subindex = ((Ihigh - Ilow) / (Chigh - Clow)) * (value - Clow) + Ilow
                return round(subindex)
    
    return breakpoints[parameter][-1][3]

def get_aqi_category(aqi_value):
    if aqi_value <= 50:
        return "Good", "The air is fresh and free from toxins. Enjoy outdoor activities without any health concerns."
    elif 51 <= aqi_value <= 100:
        return "Moderate", "Air quality is acceptable for most, but sensitive individuals might experience mild discomfort."
    elif 101 <= aqi_value <= 150:
        return "Poor", "Breathing may become slightly uncomfortable, especially for those with respiratory issues."
    elif 151 <= aqi_value <= 200:
        return "Unhealthy", "This air quality is particularly risky for children, pregnant women, and the elderly. Limit outdoor activities."
    elif 201 <= aqi_value <= 300:
        return "Severe", "Prolonged exposure can cause chronic health issues or organ damage. Avoid outdoor activities."
    else:
        return "Hazardous", "Dangerously high pollution levels. Life-threatening health risks with prolonged exposure. Stay indoors and take precautions."

# Function to fetch data for a specific location
def fetch_location_data(location_id, location_name):
    api_index = random.randint(0, 10)
    results_list = []
    
    headers = {
        "accept": "application/json",
        "X-API-Key": api_keys[api_index % len(api_keys)]
    }
    
    url = f"https://api.openaq.org/v3/locations/{location_id}/latest?limit=1000"
            
    # Get today's date in UTC
    today_utc = datetime.now(timezone.utc).date()
    yesterday_utc = today_utc - timedelta(days=1)
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()

        
        for result in data.get('results', []):
            utc_str = result['datetime']['utc']
            utc_time = datetime.fromisoformat(utc_str.replace('Z', '+00:00')).replace(tzinfo=timezone.utc)
            utc_date = utc_time.date()
            
            # Only process if the data is from today
            if utc_date == today_utc or utc_date==yesterday_utc:
                sensor_id = result.get('sensorsId', 'N/A')
                
                parameter_info = sensor_parameters.get(sensor_id, {})
                parameter_name = parameter_info.get('parameter_name', 'unknown')
                units = parameter_info.get('units', 'N/A')
                display_name = parameter_info.get('display_name', 'N/A')
                
                results_list.append({
                    'location_id': location_id,
                    'location_name': location_name,
                    'datetime_utc': utc_time,
                    'parameter': parameter_name,
                    'value': result['value'],
                    'unit': units,
                    'sensor_id': sensor_id,
                    'latitude': result['coordinates']['latitude'],
                    'longitude': result['coordinates']['longitude'],
                    'display_name': display_name
                })
        
        time.sleep(1 / len(api_keys))
        
    except requests.exceptions.RequestException as e:
        print(f"Error for location {location_id}: {e}")
        time.sleep(1)
    
    return pd.DataFrame(results_list)

# ------------------------------------
# 3. Dash App Setup
# ------------------------------------
app = dash.Dash(
    __name__,
    suppress_callback_exceptions=True,
    meta_tags=[
        {"name": "viewport", "content": "width=device-width, initial-scale=1"}
    ]
)

# Color palette for a modern dark design
colors = {
    'background': '#000000',
    'card': '#000000',
    'text': '#E0E0E0',
    'accent': '#EA7300',
    'dot':"#d96b00",
    'grid': '#444444',
    'aqi_good': 'limegreen',
    'aqi_moderate': 'gold',
    'aqi_poor': 'orange',
    'aqi_unhealthy': 'orangered',
    'aqi_severe': 'red',
    'aqi_hazardous': 'darkred'
}

# ------------------------------------
# 4. Layout Components
# ------------------------------------

# Hidden store to hold the currently selected location
selected_location_store = dcc.Store(id="selected-location", data=locations_df['location_name'].iloc[0])

# Add an Interval component to trigger periodic updates (every 60 sec)
interval_component = dcc.Interval(
    id='interval-component',
    interval=600*1000,  # 600 seconds in milliseconds
    n_intervals=0
)

# A. Header / Title
header = html.Div(
    style={
        'backgroundColor': colors['background'],
        'display': 'flex',
        'alignItems': 'center',
        'justifyContent': 'space-between',
        'padding': '10px 50px 0px 10px',
    },
    children=[
        html.Div(
            style={'display': 'flex', 'flexDirection': 'column', 'alignItems': 'flex-start', 'gap': '5px'},
            children=[
                html.Div(
                    style={'display': 'flex', 'alignItems': 'center', 'gap': '15px'},
                    children=[
                        html.Img(
                            src="/assets/revs.jpeg",
                            style={'height': '160px', 'width': 'auto'}
                        ),
                        html.Div(
                            style={'display': 'flex', 'flexDirection': 'column'},
                            children=[
                                html.H1(
                                    "AERSENSE",
                                    style={
                                        'margin': '0',
                                        'color': colors['accent'],
                                        'fontFamily': 'Orbitron, sans-serif',
                                        'fontSize': '45px',
                                        'letterSpacing': '2px',
                                        'fontWeight': '700',
                                        'textTransform': 'uppercase'
                                    }
                                ),
                                html.P(
                                    "    AQI Dashboard",
                                    style={
                                        'margin': '0',
                                        'color': colors['text'],
                                        'fontFamily': 'Orbitron, sans-serif',
                                        'fontSize': '16px',
                                        'letterSpacing': '4px',
                                        'fontWeight': '700'
                                    }
                                )
                            ]
                        )
                    ]
                )
            ]
        ),
        html.Div(
            style={
                'backgroundColor': colors['card'],
                'padding': '15px',
                'borderRadius': '6px',
                'margin': '5px'
            },
            children=[
                html.Label("Search Location:", style={'color': colors['text'], 'fontSize': '14px', 'fontFamily': 'Orbitron, sans-serif'}),
                dcc.Dropdown(
                    id='location-search',
                    options=[{'label': loc, 'value': loc} for loc in locations_df['location_name']],
                    placeholder="Select location...",
                    style={'width': '350px', 'color': '#000', 'marginTop': '5px', 'fontFamily': 'Orbitron, sans-serif'}
                )
            ]
        )
    ]
)

# B. Top Section (Map & Right-Side Info)
top_section = html.Div(
    id='top-section',
    style={'display': 'flex', 'flexDirection': 'row', 'gap': '10px 10px 10px 0', 'padding': '10px 10px 10px 0'},
    children=[
        html.Div(
            id='map-container',
            style={'width': '60%','padding': '10px'},
            children=[
                dl.Map(
                    [
                        dl.TileLayer(url="https://{s}.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png"),
                        dl.LayerGroup(id="marker-layer")
                    ],
                    center=[28.6139, 77.2090],
                    zoom=10,
                    style={'width': '100%', 'height': '75vh', 'borderRadius': '8px', 'boxShadow': '0px 0px 10px #000'}
                )
            ]
        ),
        html.Div(
            id='info-panel',
            style={'width': '40%', 'display': 'flex', 'flexDirection': 'column', 'gap': '20px','padding': '10px'},
            children=[
                html.Div(
                    id='info-card',
                    style={'backgroundColor': colors['card'], 'padding': '10px', 'borderRadius': '6px','textAlign': 'center'},
                    children=[
                        html.H2(id='location-title',
                                style={'color': colors['accent'], 'fontSize': '20px',
                                       'fontFamily': 'Orbitron, sans-serif'}),
                        html.P(id='last-updated-time',
                               style={'color': colors['text'], 'margin': '0', 'fontSize': '10px',
                                      'fontFamily': 'Orbitron, sans-serif'})
                    ]
                ),
                html.Div(
                    id='gauge-card',
                    style={'backgroundColor': colors['card'], 'padding': '50px', 'borderRadius': '6px'},
                    children=[
                        dcc.Graph(id='aqi-gauge', config={'displayModeBar': False}),
                        html.P(id='aqi-category-text',
                               style={'color': colors['text'], 'margin': '10px 0 0 0', 'fontSize': '16px',
                                      'fontFamily': 'Orbitron, sans-serif','letterSpacing': '1px'})
                    ]
                )
            ]
        )
    ]
)

# C. Bottom Section (Parameter Values)
bottom_section = html.Div(
    id='bottom-section',
    style={
        'display': 'flex', 
        'flexDirection': 'column', 
        'gap': '10px',  # Reduced gap
        'padding': '0px 10px',  # Reduced top padding
        'marginTop': '-10px',
          'overflow': 'hidden'  # Negative margin to reduce gap with top section
    },
    children=[
        html.Div(
            id='parameter-values-container',
            style={
                'width': '100%', 
                'backgroundColor': colors['card'], 
                'borderRadius': '6px', 
                'padding': '20px',
                'fontFamily': 'Orbitron, sans-serif',
                'overflow': 'hidden'
            }
        )
    ]
)
app.layout = html.Div(
    style={
        'backgroundColor': colors['background'],
        'fontFamily': 'Orbitron, sans-serif',
        'color': colors['text'],
        'margin': '0',
        'padding': '0'
    },
    children=[
        header,
        top_section,
        bottom_section,
        selected_location_store,
        interval_component
    ]
)

# ------------------------------------
# 5. Callbacks
# ------------------------------------

# A. Update Selected Location (from dropdown or marker clicks)
@app.callback(
    Output("selected-location", "data"),
    [Input("location-search", "value"),
     Input({"type": "marker", "index": ALL}, "n_clicks")],
    State("selected-location", "data")
)
def update_selected_location(search_value, marker_clicks, current_value):
    ctx = callback_context
    if not ctx.triggered:
        return current_value

    trigger = ctx.triggered[0]
    trigger_id = trigger['prop_id']
    if "location-search" in trigger_id:
        return search_value or current_value
    else:
        # Parse the triggered marker's id
        try:
            # Extract the id part before the dot and convert it into a dictionary.
            marker_id = json.loads(trigger_id.split('.')[0])
            # Return the 'index' field from the marker id which holds the location name.
            return marker_id['index']
        except Exception as e:
            print("Error parsing marker id:", e)
    return current_value

# B. Update Markers on the Map
@app.callback(
    Output("marker-layer", "children"),
    [Input("location-search", "value"),
     Input("selected-location", "data"),
     Input("interval-component", "n_intervals")]
)
def update_markers(searched_location, selected_location, n_intervals):
    markers = []
    for _, row in locations_df.iterrows():
        loc = row['location_name']
        is_selected = loc == selected_location
        
        tooltip_content = html.Div(
            children=[
                html.Strong(loc, style={"fontSize": "16px", "color": colors['accent']}),
                html.Br(),
                html.Span("Click to view data", style={"fontSize": "14px", "color": colors['text']})
            ],
            style={
                "backgroundColor": colors['card'],
                "padding": "10px",
                "borderRadius": "6px",
                "boxShadow": "0px 0px 10px rgba(0,0,0,0.5)"
            }
        )
        
        markers.append(dl.CircleMarker(
            center=[row['latitude'], row['longitude']],
            color=colors['accent'],  # Stroke (border) color is always black
            fill=True,
            fillColor='black',
            radius=8 if is_selected else 2,
            fillOpacity=0.9,
            children=[dl.Tooltip(tooltip_content, permanent=False, direction="auto", offset=[0, 15])],
            id={'type': 'marker', 'index': loc}
        ))
    return markers

# C. Update Info Panel and Parameter Values
@app.callback(
    [Output('location-title', 'children'),
     Output('last-updated-time', 'children'),
     Output('aqi-gauge', 'figure'),
     Output('aqi-category-text', 'children'),
     Output('parameter-values-container', 'children')],
    [Input('selected-location', 'data'),
     Input("interval-component", "n_intervals")]
)
def update_info_panel(selected_location, n_intervals):
    if not selected_location:
        selected_location = locations_df['location_name'].iloc[0]
    
    # Get location data
    location_row = locations_df[locations_df['location_name'] == selected_location].iloc[0]
    location_id = location_row['location_id']
    
    # Fetch latest data for the location
    location_data = fetch_location_data(location_id, selected_location)
    
    # Check if we have any data
    if location_data.empty:
        # Create an empty gauge figure
        empty_gauge_fig = go.Figure(go.Indicator(
            mode="gauge+number",
            value=0,
            title={'text': "No Data Available"},
            gauge={
                'axis': {'range': [0, 500]},
                'bar': {'color': colors['background']},
                'steps': [
                    {'range': [0, 50], 'color': colors['aqi_good']},
                    {'range': [50, 100], 'color': colors['aqi_moderate']},
                    {'range': [100, 150], 'color': colors['aqi_poor']},
                    {'range': [150, 200], 'color': colors['aqi_unhealthy']},
                    {'range': [200, 300], 'color': colors['aqi_severe']},
                    {'range': [300, 500], 'color': colors['aqi_hazardous']}
                ]
            }
        ))
        empty_gauge_fig.update_layout(
            template="plotly_dark",
            plot_bgcolor=colors['card'],
            paper_bgcolor=colors['card'],
            font_color=colors['text'],
            margin=dict(l=20, r=20, t=60, b=20),
            height=250
        )

        # Create "No Data" message layout
        no_data_message = html.Div(
            style={'textAlign': 'center'},
            children=[
                html.H2("No Data Available", 
                        style={'color': colors['text'], 'marginBottom': '5px'}),
                html.P("No current air quality data available for this location.", 
                      style={'color': colors['text'], 'fontSize': '14px'})
            ]
        )

        # Create empty parameter values layout
        empty_param_layout = [
            html.H4("Current Parameters", 
                    style={
                        'color': colors['accent'],
                        'marginBottom': '10px',
                        'textAlign': 'center',
                        'fontSize': '30px',
                        'letterSpacing': '1px',
                        'fontWeight': '600'
                    }),
            html.Div(
                html.P("No parameters data available", 
                       style={'color': colors['text'], 'textAlign': 'center'}),
                style={
                    'display': 'flex',
                    'justifyContent': 'center',
                    'width': '95%',
                    'padding': '20px'
                }
            )
        ]

        return (
            selected_location,
            "No recent updates",
            empty_gauge_fig,
            no_data_message,
            empty_param_layout
        )

    # If we have data, proceed with normal processing
    location_data['parameter'] = location_data['parameter'].map(parameter_mapping).fillna(location_data['parameter'])
    
    # Get the latest value for each parameter
    latest_data = location_data.sort_values('datetime_utc').groupby('parameter').last().reset_index()
    
    # Calculate AQI
    latest_data['aqi_subindex'] = latest_data.apply(
        lambda row: calculate_aqi_subindex(row['value'], row['parameter']), axis=1
    )
    current_aqi = latest_data['aqi_subindex'].max()
    category, description = get_aqi_category(current_aqi)
    
    # Update time
    # Update time: convert first datetime value from UTC to IST
    last_updated_time_utc = location_data['datetime_utc'].iloc[0]
    ist_tz = timezone(timedelta(hours=5, minutes=30))
    last_updated_time_ist = last_updated_time_utc.astimezone(ist_tz)
    
    # format it as a string for display:
    last_updated_time_str = last_updated_time_ist.strftime('%Y-%m-%d %H:%M:%S')
    
    # Create gauge figure
    category_color = {
        "Good": colors['aqi_good'],
        "Moderate": colors['aqi_moderate'],
        "Poor": colors['aqi_poor'],
        "Unhealthy": colors['aqi_unhealthy'],
        "Severe": colors['aqi_severe'],
        "Hazardous": colors['aqi_hazardous']
    }.get(category, colors['text'])

    gauge_fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=current_aqi,
        title={'text': "AQI"},
        gauge={
            'axis': {'range': [0, 500]},
            'bar': {'color': colors['background']},
            'steps': [
                {'range': [0, 50], 'color': colors['aqi_good']},
                {'range': [50, 100], 'color': colors['aqi_moderate']},
                {'range': [100, 150], 'color': colors['aqi_poor']},
                {'range': [150, 200], 'color': colors['aqi_unhealthy']},
                {'range': [200, 300], 'color': colors['aqi_severe']},
                {'range': [300, 500], 'color': colors['aqi_hazardous']}
            ]
        }
    ))
    gauge_fig.update_layout(
        template="plotly_dark",
        plot_bgcolor=colors['card'],
        paper_bgcolor=colors['card'],
        font_color=colors['text'],
        margin=dict(l=20, r=20, t=60, b=20),
        height=250
    )

    # Create AQI category text
    aqi_category_layout = html.Div(
        style={'textAlign': 'center'},
        children=[
            html.H2(category, style={'color': category_color, 'marginBottom': '5px'}),
            html.P(description, style={'color': colors['text'], 'fontSize': '14px'})
        ]
    )

    # Create parameter cards
    param_cards = []
    for _, row in latest_data.iterrows():
        param_cards.append(
            html.Div(
                style={
                    'backgroundColor': colors['background'],
                    'borderRadius': '5px',
                    'padding': '10px',
                    'textAlign': 'center',
                    'flex': '1',  # This makes each card take equal space
                    'border': f'1px solid {colors["grid"]}'
                },
                children=[
                    html.H5(row['parameter'], 
                        style={'margin': '0 0 5px 0', 
                                'color': colors['accent'], 
                                'fontSize': '14px'}),
                    html.P(f"{row['value']:.2f} {row['unit']}", 
                        style={'margin': '0', 
                                'fontSize': '13px'})
                ]
            )
        )

    param_values_layout = [
        html.H4("Current Parameters", 
                style={
                    'color': colors['accent'], 
                    'marginBottom': '10px',
                    'textAlign': 'center',
                    'fontSize': '30px',
                    'letterSpacing': '1px',
                    'fontWeight': '600',

                }),
        html.Div(
            param_cards, 
            style={
                'display': 'flex', 
                'flexWrap': 'nowrap',  # Changed from wrap to nowrap
                'justifyContent': 'space-between',  # Changed to space-between
                'width': '95%',
                'gap': '10px'  # Consistent gap between cards
            }
        )
    ]

    return (
        selected_location,
        f"Last Update: {last_updated_time_str}",
        gauge_fig,
        aqi_category_layout,
        param_values_layout
    )

# ------------------------------------
# 6. Run App
# ------------------------------------
if __name__ == "__main__":
    # Pick up the PORT environment variable; default to 8050 if it’s not defined.
    port = int(os.environ.get("PORT", 8050))
    app.run(host="0.0.0.0", port=port, debug=False)
