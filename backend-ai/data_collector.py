import requests
import pandas as pd
import numpy as np

PROMETHEUS_URL = "http://prometheus:9090"
JAEGER_URL = "http://jaeger:16686"

def fetch_metrics():
    # In a real scenario, this would query Prometheus for specific metrics 
    # (e.g., latency, error rate, request count) using PromQL.
    # For this MVP, we simulate fetching some metrics and mix it with real API check.
    
    try:
        res = requests.get(f"{PROMETHEUS_URL}/api/v1/query", params={'query': 'up'})
        if res.status_code == 200:
            print("Successfully connected to Prometheus")
    except Exception as e:
        print("Could not connect to Prometheus", e)
        
    # Generate synthetic training data representing [latency, request_rate, error_rate]
    # Normal data: low latency, high request rate, low error rate
    normal_data = np.random.normal(loc=[50.0, 100.0, 0.01], scale=[5.0, 10.0, 0.001], size=(100, 3))
    
    # Normalize data between 0 and 1
    # Assuming max latency 500, max req 200, max err 1.0
    normal_data[:, 0] = normal_data[:, 0] / 500.0
    normal_data[:, 1] = normal_data[:, 1] / 200.0
    normal_data[:, 2] = normal_data[:, 2] / 1.0
    
    return normal_data

def get_current_state():
    # Simulate current state metric
    # Randomly inject an anomaly for demonstration
    is_anomaly = np.random.rand() < 0.1
    if is_anomaly:
        current_data = np.array([[300.0/500.0, 50.0/200.0, 0.5/1.0]]) # high latency, low req, high error
    else:
        current_data = np.random.normal(loc=[50.0, 100.0, 0.01], scale=[5.0, 10.0, 0.001], size=(1, 3))
        current_data[:, 0] /= 500.0
        current_data[:, 1] /= 200.0
        current_data[:, 2] /= 1.0
    return current_data
