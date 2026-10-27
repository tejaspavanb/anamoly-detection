const { createService } = require('../shared/runtime');

createService({
  name: 'frontend-service',
  port: Number(process.env.PORT || 3000),
  downstream: {
    name: 'backend-service',
    url: process.env.BACKEND_URL || 'http://127.0.0.1:3001',
  },
});
