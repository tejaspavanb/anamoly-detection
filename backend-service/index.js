const express = require('express');
const app = express();
const port = 3001;

app.get('/api/data', (req, res) => {
  // Simulate some work
  setTimeout(() => {
    // 5% chance to fail
    if (Math.random() < 0.05) {
      res.status(500).json({ error: 'Internal Server Error' });
    } else {
      res.json({ message: 'Data from backend', timestamp: new Date() });
    }
  }, Math.random() * 200 + 50); // 50-250ms latency
});

// Endpoint for manual anomaly injection
app.post('/api/inject-fault', (req, res) => {
  console.log("Fault injected in backend!");
  const start = Date.now();
  while (Date.now() - start < 2000) {
    // block
  }
  res.json({ message: 'Fault executed' });
});

app.listen(port, () => {
  console.log(`Backend service listening on port ${port}`);
});
