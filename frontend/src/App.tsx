import { useEffect, useState } from 'react'
import {
  Activity, AlertTriangle, ArrowDownRight, ArrowUpRight, Boxes, CheckCircle2,
  Clock3, Factory, Gauge, RefreshCw, ShieldAlert, Wrench,
} from 'lucide-react'
import {
  Bar, BarChart, CartesianGrid, ComposedChart, Line, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts'

type TrendPoint = { date: string; oee: number }
type Kpis = {
  oee: number; availability: number; performance: number; quality: number
  total_produced: number; total_defects: number; trend: TrendPoint[]
}
type Defects = {
  total_defects: number; defect_rate: number
  pareto: { cause: string; count: number; percent: number; cumulative_percent: number }[]
}
type Downtime = { cause: string; minutes: number; events: number }
type Machine = {
  id: number; name: string; production_line: string; model: string; produced: number
  defects: number; availability: number; status: string; last_seen: string | null
}
type Alert = {
  machine_id: number; metric: string; observed_value: number; threshold: number
  severity: string; timestamp: string
}
type DashboardData = { kpis: Kpis; downtime: Downtime[]; defects: Defects; machines: Machine[]; alerts: Alert[] }

const percent = (value: number) => `${(value * 100).toFixed(1)}%`
const number = (value: number) => new Intl.NumberFormat('en-US').format(value)

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path)
  if (!response.ok) throw new Error(`Request failed (${response.status})`)
  return response.json() as Promise<T>
}

function App() {
  const [data, setData] = useState<DashboardData | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [refreshedAt, setRefreshedAt] = useState<Date | null>(null)

  async function refresh() {
    setError('')
    try {
      const [kpis, downtime, defects, machines, alerts] = await Promise.all([
        getJson<Kpis>('/api/dashboard/kpis'),
        getJson<Downtime[]>('/api/dashboard/downtime'),
        getJson<Defects>('/api/dashboard/defects'),
        getJson<Machine[]>('/api/machines'),
        getJson<Alert[]>('/api/alerts'),
      ])
      setData({ kpis, downtime, defects, machines, alerts })
      setRefreshedAt(new Date())
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Could not load dashboard data')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void refresh() }, [])

  if (loading && !data) return <div className="screen-state"><RefreshCw className="spin" /><span>Connecting to plant data</span></div>
  if (error && !data) return <div className="screen-state error-state"><ShieldAlert /><strong>Dashboard unavailable</strong><span>{error}. Check that the API and database are running.</span><button onClick={() => { setLoading(true); void refresh() }}>Retry</button></div>
  if (!data) return null

  const alerts = [...data.alerts].sort((a, b) => (a.severity === 'critical' ? -1 : 1) - (b.severity === 'critical' ? -1 : 1))
  const healthyCount = data.machines.filter(machine => machine.status === 'healthy').length

  return (
    <div className="app-shell">
      <aside className="rail">
        <div className="brand-mark"><Factory size={21} strokeWidth={2.2} /></div>
        <div className="rail-label">MFG<br />OPS</div>
        <div className="rail-rule" />
        <div className="rail-active" title="Plant overview"><Gauge size={19} /></div>
        <div className="rail-icon" title="Production"><Boxes size={19} /></div>
        <div className="rail-icon" title="Alerts"><AlertTriangle size={19} /></div>
        <div className="rail-bottom"><span className="online-dot" /><span>LIVE</span></div>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <div className="breadcrumbs"><span>Operations</span><span className="crumb-slash">/</span><strong>Plant overview</strong></div>
          <div className="topbar-right">
            <span className="connection"><span className="online-dot" /> Data connected</span>
            <button className="icon-button" title="Refresh data" onClick={() => { setLoading(true); void refresh() }}><RefreshCw size={16} /></button>
            <div className="avatar">MO</div>
          </div>
        </header>

        <section className="page-heading">
          <div>
            <div className="eyebrow"><span className="eyebrow-line" /> MANUFACTURING INTELLIGENCE</div>
            <h1>Plant performance</h1>
            <p>Production, quality and equipment health at a glance.</p>
          </div>
          <div className="period-chip"><Clock3 size={15} /> Rolling 7 days <span className="chip-divider" /> Updated {refreshedAt?.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</div>
        </section>

        {error && <div className="inline-error"><AlertTriangle size={16} /> Refresh failed: {error}<button onClick={() => void refresh()}>Try again</button></div>}

        <section className="kpi-grid" aria-label="Key performance indicators">
          <KpiCard title="Overall equipment effectiveness" value={percent(data.kpis.oee)} icon={<Gauge size={17} />} accent="green" note="Availability × performance × quality" />
          <KpiCard title="Availability" value={percent(data.kpis.availability)} icon={<Activity size={17} />} accent="blue" note="Operating time / planned time" />
          <KpiCard title="Performance" value={percent(data.kpis.performance)} icon={<ArrowUpRight size={17} />} accent="amber" note="Actual output vs ideal output" />
          <KpiCard title="Quality yield" value={percent(data.kpis.quality)} icon={<CheckCircle2 size={17} />} accent="rose" note={`${number(data.kpis.total_defects)} defects in ${number(data.kpis.total_produced)} units`} />
        </section>

        <section className="chart-grid">
          <article className="panel trend-panel">
            <PanelHeading title="OEE trend" subtitle="Daily overall equipment effectiveness" tag="14 DAYS" />
            <div className="chart trend-chart">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={data.kpis.trend} margin={{ top: 12, right: 8, bottom: 0, left: -18 }}>
                  <CartesianGrid vertical={false} stroke="#e8ede8" strokeDasharray="3 5" />
                  <XAxis dataKey="date" tickFormatter={value => new Date(`${value}T00:00:00`).toLocaleDateString('en', { month: 'short', day: 'numeric' })} tickLine={false} axisLine={false} tick={{ fill: '#87928a', fontSize: 11 }} minTickGap={25} />
                  <YAxis domain={[0, 1]} tickFormatter={value => `${Math.round(value * 100)}%`} tickLine={false} axisLine={false} tick={{ fill: '#87928a', fontSize: 11 }} />
                  <Tooltip formatter={(value) => [percent(Number(value)), 'OEE']} labelFormatter={value => new Date(`${value}T00:00:00`).toLocaleDateString()} contentStyle={{ border: '1px solid #e2e9e2', borderRadius: 6, fontSize: 12 }} />
                  <Line type="monotone" dataKey="oee" stroke="#25836b" strokeWidth={2.5} dot={false} activeDot={{ r: 4, fill: '#25836b' }} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
            <div className="chart-foot"><span className="legend-line" /> Daily OEE <span className="chart-foot-note">Calculated from aggregated production records</span></div>
          </article>

          <article className="panel downtime-panel">
            <PanelHeading title="Downtime by cause" subtitle="Lost production time · last 7 days" tag={`${data.downtime.reduce((sum, item) => sum + item.events, 0)} EVENTS`} />
            <div className="chart downtime-chart">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data.downtime} layout="vertical" margin={{ top: 6, right: 20, bottom: 0, left: 4 }}>
                  <CartesianGrid horizontal={false} stroke="#edf0ed" />
                  <XAxis type="number" tickLine={false} axisLine={false} tick={{ fill: '#87928a', fontSize: 11 }} />
                  <YAxis type="category" dataKey="cause" width={115} tickLine={false} axisLine={false} tick={{ fill: '#526057', fontSize: 11 }} />
                  <Tooltip formatter={(value) => [`${Number(value).toFixed(0)} min`, 'Downtime']} contentStyle={{ border: '1px solid #e2e9e2', borderRadius: 6, fontSize: 12 }} />
                  <Bar dataKey="minutes" fill="#e79a55" radius={[0, 4, 4, 0]} barSize={15} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="chart-foot"><span className="legend-block amber-block" /> Minutes lost <span className="chart-foot-note">By reported cause</span></div>
          </article>
        </section>

        <section className="lower-grid">
          <article className="panel pareto-panel">
            <PanelHeading title="Defect Pareto" subtitle="Where quality losses are occurring" tag={`${number(data.defects.total_defects)} DEFECTS`} />
            <div className="chart pareto-chart">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={data.defects.pareto} margin={{ top: 12, right: 12, bottom: 0, left: -12 }}>
                  <CartesianGrid vertical={false} stroke="#edf0ed" />
                  <XAxis dataKey="cause" tickLine={false} axisLine={false} tick={{ fill: '#68766c', fontSize: 10 }} interval={0} />
                  <YAxis yAxisId="count" tickLine={false} axisLine={false} tick={{ fill: '#87928a', fontSize: 10 }} />
                  <YAxis yAxisId="percent" orientation="right" domain={[0, 1]} tickFormatter={value => `${Math.round(value * 100)}%`} tickLine={false} axisLine={false} tick={{ fill: '#87928a', fontSize: 10 }} />
                  <Tooltip formatter={(value, name) => [name === 'cumulative_percent' ? percent(Number(value)) : number(Number(value)), name === 'cumulative_percent' ? 'Cumulative' : 'Defects']} contentStyle={{ border: '1px solid #e2e9e2', borderRadius: 6, fontSize: 12 }} />
                  <Bar yAxisId="count" dataKey="count" fill="#71b79e" radius={[3, 3, 0, 0]} barSize={25} />
                  <Line yAxisId="percent" dataKey="cumulative_percent" stroke="#d78148" strokeWidth={2} dot={{ r: 3, fill: '#d78148' }} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
            <div className="chart-foot"><span className="legend-block green-block" /> Defect count <span className="legend-line orange-line" /> Cumulative share</div>
          </article>

          <article className="panel alerts-panel">
            <PanelHeading title="Active alerts" subtitle="Threshold-based machine signals" tag={`${alerts.length} OPEN`} />
            <div className="alert-list">
              {alerts.length === 0 ? <div className="empty-alert"><CheckCircle2 size={19} /><span>No threshold breaches detected</span></div> : alerts.slice(0, 5).map((alert, index) => (
                <div className="alert-row" key={`${alert.machine_id}-${alert.metric}`} style={{ animationDelay: `${index * 60}ms` }}>
                  <div className={`alert-icon ${alert.severity}`}><AlertTriangle size={15} /></div>
                  <div className="alert-copy"><strong>CNC-{String(alert.machine_id).padStart(2, '0')}</strong><span>{alert.metric.replace('_', ' ')} · {percent(alert.observed_value)} vs {percent(alert.threshold)}</span></div>
                  <span className={`severity ${alert.severity}`}>{alert.severity}</span>
                </div>
              ))}
            </div>
            {alerts.length > 5 && <div className="panel-tail">+ {alerts.length - 5} more signals</div>}
          </article>
        </section>

        <section className="panel machine-panel">
          <div className="machine-heading">
            <PanelHeading title="Machine health" subtitle="Last 24 hours · production and availability" tag={`${healthyCount} / ${data.machines.length} HEALTHY`} />
            <div className="health-legend"><span><i className="health-dot good" /> Healthy</span><span><i className="health-dot watch" /> Attention</span></div>
          </div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Machine</th><th>Line</th><th>Model</th><th>Units produced</th><th>Defects</th><th>Availability</th><th>Health</th></tr></thead>
              <tbody>{data.machines.map(machine => (
                <tr key={machine.id}>
                  <td><span className="machine-name"><span className="machine-glyph"><Wrench size={13} /></span>{machine.name}</span></td>
                  <td>{machine.production_line}</td><td>{machine.model}</td>
                  <td className="numeric">{number(machine.produced)}</td>
                  <td className="numeric">{number(machine.defects)}</td>
                  <td><div className="availability-cell"><span>{percent(machine.availability)}</span><span className="meter"><i style={{ width: `${Math.min(machine.availability * 100, 100)}%` }} className={machine.availability < .75 ? 'meter-low' : ''} /></span></div></td>
                  <td><span className={`machine-status ${machine.status}`}><i />{machine.status === 'healthy' ? 'Healthy' : 'Attention'}</span></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
          <div className="table-footer"><span>Showing {data.machines.length} machines</span><span><ArrowDownRight size={14} /> Most recent 24-hour window</span></div>
        </section>

        <footer className="page-footer"><span>MANUFACTURING ANALYTICS PLATFORM</span><span>OEE = Availability × Performance × Quality</span></footer>
      </main>
    </div>
  )
}

function KpiCard({ title, value, icon, accent, note }: { title: string; value: string; icon: React.ReactNode; accent: string; note: string }) {
  return <article className={`kpi-card ${accent}`}><div className="kpi-top"><span>{title}</span><span className="kpi-icon">{icon}</span></div><div className="kpi-value">{value}</div><div className="kpi-note">{note}</div></article>
}

function PanelHeading({ title, subtitle, tag }: { title: string; subtitle: string; tag: string }) {
  return <div className="panel-heading"><div><h2>{title}</h2><p>{subtitle}</p></div><span className="panel-tag">{tag}</span></div>
}

export default App