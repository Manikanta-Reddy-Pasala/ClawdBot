function renderServiceTopology(containerId, topology) {
    const container = document.getElementById(containerId);
    if (!container || !topology) return;

    container.innerHTML = '';
    const width = container.clientWidth;
    const height = container.clientHeight || 500;

    const svg = d3.select(`#${containerId}`)
        .append('svg')
        .attr('width', width)
        .attr('height', height);

    const services = topology.services || [];
    const edges = topology.edges || [];

    // Build node map
    const nodeMap = {};
    const nodes = services.map((s, i) => {
        const node = { id: s.name, ...s, index: i };
        nodeMap[s.name] = node;
        return node;
    });

    const links = edges
        .filter(e => nodeMap[e.from] && nodeMap[e.to])
        .map(e => ({ source: e.from, target: e.to }));

    const simulation = d3.forceSimulation(nodes)
        .force('link', d3.forceLink(links).id(d => d.id).distance(120))
        .force('charge', d3.forceManyBody().strength(-600))
        .force('center', d3.forceCenter(width / 2, height / 2))
        .force('collision', d3.forceCollide().radius(55));

    // Arrow marker
    svg.append('defs').append('marker')
        .attr('id', 'arrow')
        .attr('viewBox', '0 -5 10 10')
        .attr('refX', 25)
        .attr('refY', 0)
        .attr('markerWidth', 6)
        .attr('markerHeight', 6)
        .attr('orient', 'auto')
        .append('path')
        .attr('d', 'M0,-5L10,0L0,5')
        .attr('fill', '#4a4d5a');

    const link = svg.append('g')
        .selectAll('line')
        .data(links)
        .join('line')
        .attr('stroke', '#4a4d5a')
        .attr('stroke-width', 1.5)
        .attr('marker-end', 'url(#arrow)');

    const tierColors = { critical: '#ef4444', important: '#f59e0b', standard: '#6366f1' };

    const node = svg.append('g')
        .selectAll('g')
        .data(nodes)
        .join('g')
        .call(d3.drag()
            .on('start', (event, d) => { if (!event.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
            .on('drag', (event, d) => { d.fx = event.x; d.fy = event.y; })
            .on('end', (event, d) => { if (!event.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; })
        );

    node.append('circle')
        .attr('r', d => d.tier === 'critical' ? 18 : d.tier === 'important' ? 14 : 10)
        .attr('fill', d => tierColors[d.tier] || '#6366f1')
        .attr('opacity', 0.8)
        .attr('stroke', '#fff')
        .attr('stroke-width', 1.5);

    node.append('text')
        .text(d => d.name.length > 15 ? d.name.substring(0, 13) + '..' : d.name)
        .attr('dy', d => (d.tier === 'critical' ? 18 : 14) + 14)
        .attr('text-anchor', 'middle')
        .attr('fill', '#e1e4ea')
        .attr('font-size', '10px');

    node.append('title').text(d => `${d.name}\nNamespace: ${d.namespace}\nTier: ${d.tier}\nPort: ${d.port}`);

    simulation.on('tick', () => {
        link
            .attr('x1', d => d.source.x)
            .attr('y1', d => d.source.y)
            .attr('x2', d => d.target.x)
            .attr('y2', d => d.target.y);
        node.attr('transform', d => `translate(${d.x},${d.y})`);
    });
}
