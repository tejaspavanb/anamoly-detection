const express = require('express');
const http = require('http');
const app = express();
const port = 3000;

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:3001';

app.get('/', (req, res) => {
  http.get(`${BACKEND_URL}/api/data`, (response) => {
    let data = '';
    response.on('data', (chunk) => {
      data += chunk;
    });
    response.on('end', () => {
      if (response.statusCode === 200) {
        res.json({ message: 'Frontend successfully called backend', backendResponse: JSON.parse(data) });
      } else {
        res.status(response.statusCode).json({ error: 'Backend failed', details: data });
      }
    });
  }).on('error', (err) => {
    res.status(500).json({ error: 'Failed to connect to backend' });
  });
});

app.listen(port, () => {
  console.log(`Frontend service listening on port ${port}`);
});
