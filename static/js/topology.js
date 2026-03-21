/**
 * Layered service topology visualization.
 * Groups services by namespace with swim-lane backgrounds,
 * arranges in logical tiers (top-to-bottom: clients -> gateway -> services -> core -> infra).
 */
function renderServiceTopology(containerId, topology) {
    const container = document.getElementById(containerId);
    if (!container || !topology) return;

    container.innerHTML = '';

    const services = topology.services || [];
    const edges = topology.edges || [];
    if (!services.length) return;

    // --- Assign layers based on tier + role ---
    const layerOrder = {
        'frontend': 0,
        'gateway': 1,
        'business': 2,
        'core': 3,
        'infra': 4,
    };

    const frontendNames = new Set(['PosFrontend', 'PosAdmin', 'PosHome']);
    const gatewayNames = new Set(['GatewayService']);
    const coreNames = new Set(['PosClientBackend', 'PosServerBackend', 'PosDataSyncService']);
    const infraNames = new Set([
        'MongoDbService', 'nats-server', 'redpanda', 'debezium-connect',
        'mongodb-cluster', 'Typesense', 'AzureOCR', 'dragonfly',
    ]);

    function getLayer(svc) {
        if (frontendNames.has(svc.name)) return 'frontend';
        if (gatewayNames.has(svc.name)) return 'gateway';
        if (infraNames.has(svc.name)) return 'infra';
        if (coreNames.has(svc.name)) return 'core';
        return 'business';
    }

    // --- Group by layer ---
    const layers = { frontend: [], gateway: [], business: [], core: [], infra: [] };
    const nodeMap = {};
    services.forEach(s => {
        const layer = getLayer(s);
        const node = { ...s, layer };
        layers[layer].push(node);
        nodeMap[s.name] = node;
    });

    // --- Layout constants ---
    const nodeW = 136, nodeH = 50;
    const layerPadY = 22, layerPadX = 16;
    const gapX = 14, gapY = 12;
    const layerGap = 16;

    // Use full viewport width for topology
    const width = Math.max(window.innerWidth - 20, 1400);

    const namespaceColors = {
        'default': { bg: 'rgba(99,102,241,0.06)', border: 'rgba(99,102,241,0.25)', text: '#818cf8' },
        'pos': { bg: 'rgba(34,197,94,0.06)', border: 'rgba(34,197,94,0.25)', text: '#4ade80' },
        'kafka': { bg: 'rgba(249,115,22,0.06)', border: 'rgba(249,115,22,0.25)', text: '#fb923c' },
        'mongodb': { bg: 'rgba(234,179,8,0.06)', border: 'rgba(234,179,8,0.25)', text: '#facc15' },
    };

    const tierColors = {
        'critical': '#ef4444',
        'important': '#f59e0b',
        'standard': '#6366f1',
    };

    const layerLabels = {
        frontend: 'Client Apps',
        gateway: 'API Gateway',
        business: 'Business Services',
        core: 'Core Backend',
        infra: 'Infrastructure',
    };

    // --- Helper: lay out nodes in a namespace group, wrapping rows ---
    function layoutNsGroup(items, startX, startY, maxWidth) {
        const rows = [];
        let row = [];
        let rowW = layerPadX;

        items.forEach(node => {
            const needed = nodeW + gapX;
            if (row.length > 0 && rowW + needed > maxWidth - layerPadX) {
                rows.push(row);
                row = [];
                rowW = layerPadX;
            }
            row.push(node);
            rowW += needed;
        });
        if (row.length) rows.push(row);

        const rowH = nodeH + gapY;
        const groupH = rows.length * rowH - gapY + layerPadY * 2;

        // Widest row determines group width
        let maxRowW = 0;
        rows.forEach(r => {
            const w = r.length * (nodeW + gapX) - gapX;
            if (w > maxRowW) maxRowW = w;
        });
        const groupW = maxRowW + layerPadX * 2;

        // Position each node
        rows.forEach((r, ri) => {
            const rowWidth = r.length * (nodeW + gapX) - gapX;
            const rowStartX = startX + layerPadX + (maxRowW - rowWidth) / 2;
            r.forEach((node, ci) => {
                node.x = rowStartX + ci * (nodeW + gapX) + nodeW / 2;
                node.y = startY + layerPadY + ri * rowH + nodeH / 2;
            });
        });

        return { groupW, groupH };
    }

    // --- Compute positions ---
    let currentY = 20;
    const layerBounds = {};

    Object.keys(layerOrder).forEach(layerName => {
        const nodes = layers[layerName];
        if (!nodes.length) return;

        // Group by namespace within layer
        const nsByNs = {};
        nodes.forEach(n => {
            const ns = n.namespace || 'default';
            if (!nsByNs[ns]) nsByNs[ns] = [];
            nsByNs[ns].push(n);
        });

        const nsGroups = Object.entries(nsByNs);

        // Determine available width for this layer's namespace groups
        const availW = width - 40;

        // Check if all groups can fit side by side in single rows
        let totalSingleRowW = 0;
        nsGroups.forEach(([, items]) => {
            totalSingleRowW += items.length * (nodeW + gapX) - gapX + layerPadX * 2;
        });
        totalSingleRowW += (nsGroups.length - 1) * gapX;
        const allFitSingleRow = totalSingleRowW <= availW;

        const groupSizes = [];
        if (allFitSingleRow) {
            // All fit in single rows side by side
            nsGroups.forEach(([ns, items]) => {
                const maxGroupW = items.length * (nodeW + gapX) - gapX + layerPadX * 2;
                const sz = layoutNsGroup(items, 0, 0, maxGroupW);
                groupSizes.push({ ns, items, ...sz });
            });
        } else {
            // Too many — merge all into one flat layout, draw ns backgrounds after
            const allItems = [];
            nsGroups.forEach(([ns, items]) => items.forEach(n => { n._ns = ns; allItems.push(n); }));
            // Sort: default namespace first
            allItems.sort((a, b) => (a._ns === 'default' ? 0 : 1) - (b._ns === 'default' ? 0 : 1));
            layoutNsGroup(allItems, 0, 0, availW);
            // Create a single "merged" group
            groupSizes.push({ ns: '_merged', items: allItems, groupW: availW, groupH: 0 });
        }

        // Total width of all groups
        let totalGroupW = 0;
        groupSizes.forEach(g => totalGroupW += g.groupW);
        totalGroupW += (groupSizes.length - 1) * gapX;

        // Center groups
        let nsX = Math.max(layerPadX, (width - totalGroupW) / 2);

        let maxGroupH = 0;
        groupSizes.forEach((g) => {
            const { ns, items, groupW } = g;

            // Re-layout at the actual position (add padding so wrapping matches first pass)
            const sz = layoutNsGroup(items, nsX, currentY, groupW + layerPadX * 2);

            if (ns === '_merged') {
                // For merged layout, compute bounding box per actual namespace
                const nsBounds = {};
                items.forEach(node => {
                    const actualNs = node._ns || node.namespace || 'default';
                    node._ns = actualNs;
                    if (!nsBounds[actualNs]) {
                        nsBounds[actualNs] = { minX: Infinity, maxX: -Infinity, minY: Infinity, maxY: -Infinity };
                    }
                    const b = nsBounds[actualNs];
                    b.minX = Math.min(b.minX, node.x - nodeW / 2);
                    b.maxX = Math.max(b.maxX, node.x + nodeW / 2);
                    b.minY = Math.min(b.minY, node.y - nodeH / 2);
                    b.maxY = Math.max(b.maxY, node.y + nodeH / 2);
                });
                // Set group bounds to full layer
                items.forEach(node => {
                    node._groupX = nsX;
                    node._groupW = sz.groupW;
                    node._groupY = currentY;
                    node._groupH = sz.groupH;
                    // Override with per-namespace bounds for background drawing
                    const b = nsBounds[node._ns];
                    if (b) {
                        node._nsGroupX = b.minX - 8;
                        node._nsGroupW = b.maxX - b.minX + 16;
                        node._nsGroupY = b.minY - 8;
                        node._nsGroupH = b.maxY - b.minY + 16;
                    }
                });
                if (sz.groupH > maxGroupH) maxGroupH = sz.groupH;
            } else {
                items.forEach(node => {
                    if (!node._ns) node._ns = ns;
                    node._groupX = nsX;
                    node._groupW = sz.groupW;
                    node._groupY = currentY;
                    node._groupH = sz.groupH;
                });
                if (sz.groupH > maxGroupH) maxGroupH = sz.groupH;
            }

            nsX += sz.groupW + gapX;
        });

        // Make all groups in this layer the same height
        groupSizes.forEach(g => {
            g.items.forEach(node => {
                node._groupH = maxGroupH;
            });
        });

        layerBounds[layerName] = {
            y: currentY,
            h: maxGroupH,
            label: layerLabels[layerName],
        };
        currentY += maxGroupH + layerGap;
    });

    const totalHeight = currentY + 20;

    // --- Create SVG ---
    const svg = d3.select(`#${containerId}`)
        .append('svg')
        .attr('width', '100%')
        .attr('height', totalHeight)
        .attr('viewBox', `0 0 ${width} ${totalHeight}`)
        .attr('preserveAspectRatio', 'xMidYMin meet');

    // --- Defs: arrow markers, glow filter ---
    const defs = svg.append('defs');

    ['critical', 'important', 'standard'].forEach(tier => {
        defs.append('marker')
            .attr('id', `arrow-${tier}`)
            .attr('viewBox', '0 -4 8 8')
            .attr('refX', 8)
            .attr('refY', 0)
            .attr('markerWidth', 7)
            .attr('markerHeight', 7)
            .attr('orient', 'auto')
            .append('path')
            .attr('d', 'M0,-4L8,0L0,4Z')
            .attr('fill', tierColors[tier] || '#4a4d5a')
            .attr('opacity', 0.6);
    });

    // Glow filter for critical nodes
    const glow = defs.append('filter').attr('id', 'glow');
    glow.append('feGaussianBlur').attr('stdDeviation', '3').attr('result', 'blur');
    glow.append('feMerge').selectAll('feMergeNode')
        .data(['blur', 'SourceGraphic']).join('feMergeNode').attr('in', d => d);

    // --- Layer backgrounds ---
    Object.entries(layerBounds).forEach(([, bounds]) => {
        svg.append('rect')
            .attr('x', 8).attr('y', bounds.y)
            .attr('width', width - 16).attr('height', bounds.h)
            .attr('rx', 8)
            .attr('fill', 'rgba(255,255,255,0.02)')
            .attr('stroke', 'rgba(255,255,255,0.06)')
            .attr('stroke-width', 1);

        svg.append('text')
            .attr('x', 16).attr('y', bounds.y + 16)
            .attr('fill', 'rgba(255,255,255,0.3)')
            .attr('font-size', '11px')
            .attr('font-weight', '600')
            .text(bounds.label);
    });

    // --- Namespace group backgrounds ---
    const drawnGroups = new Set();
    services.forEach(s => {
        const node = nodeMap[s.name];
        if (!node || !node._groupX) return;

        // Use per-namespace bounds if available (merged layout), otherwise group bounds
        const gx = node._nsGroupX !== undefined ? node._nsGroupX : node._groupX;
        const gy = node._nsGroupY !== undefined ? node._nsGroupY : node._groupY;
        const gw = node._nsGroupW !== undefined ? node._nsGroupW : node._groupW;
        const gh = node._nsGroupH !== undefined ? node._nsGroupH : node._groupH;
        const key = `${node._ns}-${Math.round(gx)}-${Math.round(gy)}`;
        if (drawnGroups.has(key)) return;
        drawnGroups.add(key);

        const nsColor = namespaceColors[node._ns] || namespaceColors.default;
        svg.append('rect')
            .attr('x', gx).attr('y', gy)
            .attr('width', gw).attr('height', gh)
            .attr('rx', 6)
            .attr('fill', nsColor.bg)
            .attr('stroke', nsColor.border)
            .attr('stroke-width', 1)
            .attr('stroke-dasharray', '4,3');

        // Namespace label (bottom-right)
        svg.append('text')
            .attr('x', gx + gw - 6)
            .attr('y', gy + gh - 4)
            .attr('text-anchor', 'end')
            .attr('fill', nsColor.text)
            .attr('font-size', '9px')
            .attr('opacity', 0.7)
            .text(node._ns);
    });

    // --- Edges (curved) ---
    const linkG = svg.append('g').attr('class', 'links');

    edges.forEach(e => {
        const src = nodeMap[e.from];
        const tgt = nodeMap[e.to];
        if (!src || !tgt || !src.x || !tgt.x) return;

        const edgeTier = src.tier || 'standard';

        // Curved path from source bottom to target top
        const x1 = src.x, y1 = src.y + nodeH / 2;
        const x2 = tgt.x, y2 = tgt.y - nodeH / 2;
        const midY = (y1 + y2) / 2;

        const path = `M${x1},${y1} C${x1},${midY} ${x2},${midY} ${x2},${y2}`;

        linkG.append('path')
            .attr('d', path)
            .attr('fill', 'none')
            .attr('stroke', tierColors[edgeTier] || '#4a4d5a')
            .attr('stroke-width', 1.5)
            .attr('stroke-opacity', 0.35)
            .attr('marker-end', `url(#arrow-${edgeTier})`);
    });

    // --- Service nodes ---
    const nodeG = svg.append('g').attr('class', 'nodes');

    services.forEach(s => {
        const node = nodeMap[s.name];
        if (!node || !node.x) return;

        const g = nodeG.append('g')
            .attr('transform', `translate(${node.x},${node.y})`)
            .attr('class', 'service-node')
            .style('cursor', 'pointer');

        // Card background
        const color = tierColors[node.tier] || tierColors.standard;
        g.append('rect')
            .attr('x', -nodeW / 2).attr('y', -nodeH / 2)
            .attr('width', nodeW).attr('height', nodeH)
            .attr('rx', 8)
            .attr('fill', 'rgba(30,32,44,0.95)')
            .attr('stroke', color)
            .attr('stroke-width', node.tier === 'critical' ? 2 : 1.5)
            .attr('stroke-opacity', node.tier === 'critical' ? 0.8 : 0.5);

        if (node.tier === 'critical') {
            g.select('rect').attr('filter', 'url(#glow)');
        }

        // Tier indicator dot
        g.append('circle')
            .attr('cx', -nodeW / 2 + 10).attr('cy', -nodeH / 2 + 10)
            .attr('r', 3.5)
            .attr('fill', color);

        // Service name
        const displayName = s.name.length > 18 ? s.name.substring(0, 16) + '..' : s.name;
        g.append('text')
            .attr('x', 0).attr('y', -3)
            .attr('text-anchor', 'middle')
            .attr('fill', '#e1e4ea')
            .attr('font-size', '10.5px')
            .attr('font-weight', '600')
            .text(displayName);

        // Port + tier label
        g.append('text')
            .attr('x', 0).attr('y', 12)
            .attr('text-anchor', 'middle')
            .attr('fill', 'rgba(255,255,255,0.4)')
            .attr('font-size', '9px')
            .text(`:${node.port} | ${node.tier}`);

        // Tooltip
        g.append('title').text(
            `${s.name}\nNamespace: ${node.namespace}\nTier: ${node.tier}\nPort: ${node.port}\nReplicas: ${node.replicas || 1}\nDeps: ${(node.dependencies || []).join(', ') || 'none'}`
        );

        // Hover effect
        g.on('mouseover', function () {
            d3.select(this).select('rect')
                .transition().duration(150)
                .attr('stroke-opacity', 1)
                .attr('fill', 'rgba(40,42,56,0.98)');
            highlightEdges(s.name, true);
        })
        .on('mouseout', function () {
            d3.select(this).select('rect')
                .transition().duration(150)
                .attr('stroke-opacity', node.tier === 'critical' ? 0.8 : 0.5)
                .attr('fill', 'rgba(30,32,44,0.95)');
            highlightEdges(s.name, false);
        });
    });

    function highlightEdges(serviceName, highlight) {
        linkG.selectAll('path').each(function () {
            const path = d3.select(this);
            const src = edges.find(e => {
                const sNode = nodeMap[e.from];
                const tNode = nodeMap[e.to];
                if (!sNode || !tNode) return false;
                return (e.from === serviceName || e.to === serviceName);
            });
            if (src && (src.from === serviceName || src.to === serviceName)) {
                path.attr('stroke-opacity', highlight ? 0.9 : 0.35)
                    .attr('stroke-width', highlight ? 2.5 : 1.5);
            }
        });
    }

    // --- Legend ---
    const legendG = svg.append('g')
        .attr('transform', `translate(${width - 220}, ${totalHeight - 70})`);

    legendG.append('rect')
        .attr('x', -8).attr('y', -8)
        .attr('width', 210).attr('height', 66)
        .attr('rx', 6)
        .attr('fill', 'rgba(30,32,44,0.9)')
        .attr('stroke', 'rgba(255,255,255,0.1)');

    [
        { label: 'Critical', color: tierColors.critical, y: 8 },
        { label: 'Important', color: tierColors.important, y: 24 },
        { label: 'Standard', color: tierColors.standard, y: 40 },
    ].forEach(item => {
        legendG.append('circle').attr('cx', 8).attr('cy', item.y).attr('r', 5).attr('fill', item.color);
        legendG.append('text').attr('x', 20).attr('y', item.y + 4).attr('fill', '#aaa').attr('font-size', '10px').text(item.label);
    });

    // Namespace legend
    let nsLX = 90;
    Object.entries(namespaceColors).forEach(([ns, c]) => {
        legendG.append('rect').attr('x', nsLX).attr('y', 2).attr('width', 8).attr('height', 8).attr('fill', c.border).attr('rx', 2);
        legendG.append('text').attr('x', nsLX + 12).attr('y', 10).attr('fill', c.text).attr('font-size', '9px').text(ns);
        nsLX += 10 + ns.length * 5 + 8;
    });
}
