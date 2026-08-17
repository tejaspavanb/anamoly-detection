from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import torch
import torch.nn as nn
from model import Autoencoder, calculate_anomaly_score
from data_collector import fetch_metrics, get_current_state
import numpy as np

app = FastAPI(title="Microservice Anomaly Detection API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global model and threshold
model = None
threshold = 0.05

@app.on_event("startup")
async def startup_event():
    global model, threshold
    print("Initializing AI Model...")
    # Fetch training data
    training_data = fetch_metrics()
    tensor_data = torch.FloatTensor(training_data)
    
    # Initialize and train model
    input_dim = tensor_data.shape[1]
    model = Autoencoder(input_dim)
    optimizer = torch.optim.Adam(model.parameters(), lr=0.01)
    criterion = nn.MSELoss()
    
    # Simple training loop
    for epoch in range(100):
        optimizer.zero_grad()
        output = model(tensor_data)
        loss = criterion(output, tensor_data)
        loss.backward()
        optimizer.step()
        
    print("Model training complete.")
    
    # Calculate threshold based on 95th percentile of training loss
    scores = calculate_anomaly_score(model, tensor_data)
    threshold = np.percentile(scores, 95)
    print(f"Anomaly threshold set to {threshold}")

@app.get("/api/anomaly/status")
async def get_anomaly_status():
    current_data = get_current_state()
    tensor_data = torch.FloatTensor(current_data)
    score = calculate_anomaly_score(model, tensor_data)[0]
    
    is_anomaly = bool(score > threshold)
    confidence = min(100.0, (score / threshold) * 50) if is_anomaly else 99.0
    
    # For a real implementation, root cause would be derived from tracing (Jaeger)
    # and feature importance from the Autoencoder or a GNN.
    root_cause = "backend-service" if is_anomaly else None
    
    return {
        "anomaly_detected": is_anomaly,
        "anomaly_score": float(score),
        "threshold": float(threshold),
        "confidence": float(confidence),
        "root_cause": root_cause,
        "metrics": {
            "latency": float(current_data[0][0] * 500),
            "request_rate": float(current_data[0][1] * 200),
            "error_rate": float(current_data[0][2] * 1.0)
        }
    }
