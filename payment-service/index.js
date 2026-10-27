const { createService } = require('../shared/runtime');

// Leaf of the chain so a downstream failure shows up in backend and gateway logs.
createService({
  name: 'payment-service',
  port: Number(process.env.PORT || 3002),
});
