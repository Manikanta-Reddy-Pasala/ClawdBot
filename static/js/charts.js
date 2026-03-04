class ServiceStatusChart {
    constructor(canvasId) {
        this.canvasId = canvasId;
        this.chart = null;
    }

    init() {
        const ctx = document.getElementById(this.canvasId);
        if (!ctx) return;
        if (this.chart) { this.chart.destroy(); this.chart = null; }
        const existing = Chart.getChart(ctx);
        if (existing) existing.destroy();

        this.chart = new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: ['Healthy', 'Degraded', 'Critical'],
                datasets: [{
                    data: [0, 0, 0],
                    backgroundColor: ['#22c55e', '#f59e0b', '#ef4444'],
                    borderWidth: 0,
                    hoverOffset: 6,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: '65%',
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: { color: '#8b8fa3', padding: 16, usePointStyle: true, pointStyleWidth: 10 },
                    },
                },
                animation: { duration: 400 },
            }
        });
    }

    update(healthy, degraded, critical) {
        if (!this.chart) return;
        try {
            this.chart.data.datasets[0].data = [healthy, degraded, critical];
            this.chart.update('none');
        } catch (e) {
            // Chart not ready yet, reinitialize
            this.chart.destroy();
            this.chart = null;
            this.init();
        }
    }
}
