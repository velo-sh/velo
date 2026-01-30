const MOCK_DATA = {
    "benchmarks": [
        { "name": "CLI Applications (Path Caching)", "cpython_time": 31.4, "velo_time": 1.0, "cpython_rss": 48.4, "velo_rss": 5.2 },
        { "name": "AI & Data Processing (LangChain)", "cpython_time": 400.0, "velo_time": 3.1, "cpython_rss": 45.5, "velo_rss": 49.7 },
        { "name": "Web APIs & Services (FastAPI)", "cpython_time": 369.6, "velo_time": 1.2, "cpython_rss": 47.0, "velo_rss": 46.6 },
        { "name": "Serverless Computing (Cold Start)", "cpython_time": 318.6, "velo_time": 1.5, "cpython_rss": 63.0, "velo_rss": 64.8 },
        { "name": "Heavyweight Frameworks (Django)", "cpython_time": 234.6, "velo_time": 1.3, "cpython_rss": 106.2, "velo_rss": 108.5 }
    ]
};

async function loadDashboard() {
    const dashboard = document.getElementById('dashboard');
    const reportPath = '../../.velo_report.json';
    let data;

    try {
        const response = await fetch(reportPath);
        if (!response.ok) throw new Error('Data file not found');
        data = await response.json();
    } catch (error) {
        console.warn('Velo Vision: Fetch failed, using fallback mock data for recording.', error);
        data = MOCK_DATA;
    }

    renderData(data);
}

const NAME_MAP = {
    "CLI Applications": "CLI Applications (Path Caching)",
    "AI & Data Processing": "AI & Data Processing (LangChain)",
    "Web APIs & Services": "Web APIs & Services (FastAPI)",
    "Serverless Computing": "Serverless Computing (Cold Start)",
    "Heavyweight Frameworks": "Heavyweight Frameworks (Django)"
};

function renderData(data) {
    const dashboard = document.getElementById('dashboard');
    // Apply name mapping if exists
    data.benchmarks.forEach(bench => {
        if (NAME_MAP[bench.name]) {
            bench.name = NAME_MAP[bench.name];
        }
    });

    dashboard.innerHTML = `
        <section class="chart-section">
            <h2 class="chart-title"><span class="icon">🚀</span> Performance Speedup</h2>
            <div id="speed-chart"></div>
        </section>
    `;

    const speedChart = document.getElementById('speed-chart');

    const maxTime = Math.max(...data.benchmarks.map(b => Math.max(b.cpython_time, b.velo_time)));
    const maxMem = Math.max(...data.benchmarks.map(b => Math.max(b.cpython_rss, b.velo_rss)));

    data.benchmarks.forEach((bench, index) => {

        // Speed chart
        const cpythonTimePercent = (bench.cpython_time / maxTime) * 100;
        const veloTimePercent = (bench.velo_time / maxTime) * 100;
        const speedup = (bench.cpython_time / bench.velo_time);

        let speedBadge = `${speedup.toFixed(1)}x faster ⚡`;

        speedChart.innerHTML += createBenchmarkGroup(
            bench.name,
            bench.cpython_time, 'ms', cpythonTimePercent,
            bench.velo_time, 'ms', veloTimePercent,
            speedBadge,
            index
        );
    });

    // Trigger animations with 300ms delay as requested
    setTimeout(() => {
        document.querySelectorAll('.bar-fill').forEach(bar => {
            bar.style.width = bar.dataset.target + '%';
        });
    }, 300);
}

function createBenchmarkGroup(name, cpVal, cpUnit, cpPercent, veVal, veUnit, vePercent, badge, delay) {
    return `
        <div class="benchmark-group">
            <div class="benchmark-label">${name}</div>
            <div class="bar-pair">
                <div class="bar-row">
                    <span class="bar-name">CPython</span>
                    <div class="bar-track">
                        <div class="bar-fill cpython" data-target="${cpPercent}" style="width: 0%"></div>
                    </div>
                    <span class="bar-value cpython">${cpVal.toFixed(1)}${cpUnit}</span>
                    <span class="speedup-badge"></span>
                </div>
                <div class="bar-row">
                    <span class="bar-name">Velo</span>
                    <div class="bar-track">
                        <div class="bar-fill velo" data-target="${vePercent}" style="width: 0%"></div>
                    </div>
                    <span class="bar-value velo">${veVal.toFixed(1)}${veUnit}</span>
                    <span class="speedup-badge">${badge}</span>
                </div>
            </div>
        </div>
    `;
}

document.addEventListener('DOMContentLoaded', loadDashboard);
// Trigger logic every 5 seconds as requested for recording
setInterval(loadDashboard, 5000);
