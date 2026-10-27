const { createService } = require('../shared/runtime');

createService({
  name: 'backend-service',
  port: Number(process.env.PORT || 3001),
  downstream: {
    name: 'payment-service',
    url: process.env.PAYMENT_URL || 'http://127.0.0.1:3002',
  },
});
