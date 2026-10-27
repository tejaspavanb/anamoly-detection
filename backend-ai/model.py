import numpy as np

SERVICE_NAMES = ("frontend-service", "backend-service", "payment-service")


class Autoencoder:
    """Bottleneck autoencoder. Linear decoder keeps error on the 0–1 feature scale."""

    def __init__(self, input_dim, seed=7):
        rng = np.random.default_rng(seed)
        self.shapes = ((input_dim, 8), (8, 3), (3, 8), (8, input_dim))
        self.weights = []
        self.biases = []
        for fan_in, fan_out in self.shapes:
            self.weights.append(rng.normal(0, 1 / np.sqrt(fan_in), size=(fan_in, fan_out)))
            self.biases.append(np.zeros(fan_out))
        self.threshold = 0.05

    def _forward(self, x):
        activations = [x]
        pre = []
        for i, (weight, bias) in enumerate(zip(self.weights, self.biases)):
            z = activations[-1] @ weight + bias
            pre.append(z)
            if i < len(self.weights) - 1:
                activations.append(np.maximum(z, 0))
            else:
                activations.append(z)
        return activations, pre

    def fit(self, data, epochs=600, lr=0.08):
        x = np.asarray(data, dtype=np.float64)
        n, dim = x.shape
        for _ in range(epochs):
            activations, pre = self._forward(x)
            y = activations[-1]
            delta = (2.0 / (n * dim)) * (y - x)
            for layer in range(len(self.weights) - 1, -1, -1):
                incoming = activations[layer]
                grad_w = incoming.T @ delta
                grad_b = delta.sum(axis=0)
                if layer > 0:
                    delta = (delta @ self.weights[layer].T) * (pre[layer - 1] > 0)
                self.weights[layer] -= lr * grad_w
                self.biases[layer] -= lr * grad_b

        normal_scores = self.score(x)
        self.threshold = float(np.percentile(normal_scores, 99) + 1e-4)
        return self

    def calibrate(self, normal, anomaly):
        normal_hi = float(np.percentile(self.score(normal), 99))
        anomaly_lo = float(np.percentile(self.score(anomaly), 10))
        if anomaly_lo > normal_hi:
            self.threshold = (normal_hi + anomaly_lo) / 2
        else:
            self.threshold = normal_hi * 2 + 1e-4
        return self.threshold, normal_hi, anomaly_lo

    def reconstruct(self, data):
        activations, _ = self._forward(np.asarray(data, dtype=np.float64))
        return activations[-1]

    def score(self, data):
        x = np.asarray(data, dtype=np.float64)
        if x.ndim == 1:
            x = x.reshape(1, -1)
        y = self.reconstruct(x)
        return np.mean((y - x) ** 2, axis=1)

    def attribute(self, vector):
        x = np.asarray(vector, dtype=np.float64).reshape(-1)
        error = (x - self.reconstruct(x.reshape(1, -1))[0]) ** 2
        scores = {
            name: float(error[i * 3:(i + 1) * 3].mean())
            for i, name in enumerate(SERVICE_NAMES)
        }
        root = max(scores, key=scores.get)
        return root, scores


def synthetic_sets(n=500, seed=3):
    rng = np.random.default_rng(seed)
    normal = np.column_stack([
        rng.normal(0.055, 0.018, n),
        rng.normal(0.02, 0.012, n),
        rng.normal(0.40, 0.07, n),
        rng.normal(0.038, 0.014, n),
        rng.normal(0.015, 0.01, n),
        rng.normal(0.40, 0.07, n),
        rng.normal(0.022, 0.01, n),
        rng.normal(0.01, 0.008, n),
        rng.normal(0.40, 0.07, n),
    ])
    latency = normal.copy()
    latency[:, 6] = rng.uniform(0.65, 0.95, n)
    latency[:, 3] = latency[:, 6] + rng.normal(0.02, 0.01, n)
    latency[:, 0] = latency[:, 3] + rng.normal(0.02, 0.01, n)
    errors = normal.copy()
    errors[:, [1, 4, 7]] = rng.uniform(0.55, 0.98, (n, 3))
    crash = normal.copy()
    crash[:, 7] = rng.uniform(0.85, 1.0, n)
    crash[:, 4] = rng.uniform(0.7, 1.0, n)
    crash[:, 1] = rng.uniform(0.7, 1.0, n)
    crash[:, 8] = rng.uniform(0.0, 0.08, n)
    anomaly = np.vstack([latency, errors, crash])
    return np.clip(normal, 0, 1), np.clip(anomaly, 0, 1)


def build_model():
    normal, anomaly = synthetic_sets()
    model = Autoencoder(normal.shape[1])
    model.fit(normal)
    threshold, normal_hi, anomaly_lo = model.calibrate(normal, anomaly)
    print(
        f"Autoencoder ready. threshold={threshold:.5f} "
        f"normal_p99={normal_hi:.5f} anomaly_p10={anomaly_lo:.5f}"
    )
    return model


if __name__ == "__main__":
    model = build_model()
    normal, anomaly = synthetic_sets(80, seed=9)
    assert np.percentile(model.score(anomaly), 10) > model.threshold
    assert np.percentile(model.score(normal), 95) < model.threshold
    print("separation ok", model.threshold)
