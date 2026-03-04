class DashboardWebSocket {
    constructor(onMessage, onStatusChange) {
        this.onMessage = onMessage;
        this.onStatusChange = onStatusChange;
        this.ws = null;
        this.reconnectDelay = 2000;
    }

    connect() {
        const proto = location.protocol === 'https:' ? 'wss' : 'ws';
        const url = `${proto}://${location.host}/api/v1/dashboard/ws`;
        try {
            this.ws = new WebSocket(url);
            this.ws.onopen = () => {
                this.onStatusChange(true);
                this.reconnectDelay = 2000;
            };
            this.ws.onmessage = (e) => {
                try {
                    const msg = JSON.parse(e.data);
                    this.onMessage(msg.event, msg.data);
                } catch {}
            };
            this.ws.onclose = () => {
                this.onStatusChange(false);
                setTimeout(() => this.connect(), this.reconnectDelay);
                this.reconnectDelay = Math.min(this.reconnectDelay * 1.5, 30000);
            };
            this.ws.onerror = () => this.ws.close();
        } catch {
            this.onStatusChange(false);
            setTimeout(() => this.connect(), this.reconnectDelay);
        }
    }

    send(data) {
        if (this.ws?.readyState === WebSocket.OPEN) {
            this.ws.send(typeof data === 'string' ? data : JSON.stringify(data));
        }
    }
}
