import React, { useEffect, useRef } from "react";
import { Chart, ArcElement, Tooltip, Legend, PieController } from "chart.js";

Chart.register(ArcElement, Tooltip, Legend, PieController);

const PBCC_DATA = "https://pbcc.blob.core.windows.net/pbcc-data";

function PieChart({ id, data, labels, colours }) {
  const canvasRef = useRef(null);
  const chartRef = useRef(null);

  useEffect(() => {
    if (chartRef.current) chartRef.current.destroy();
    if (!data || data.every((v) => !v)) return;
    chartRef.current = new Chart(canvasRef.current, {
      type: "pie",
      data: {
        labels,
        datasets: [{ data, backgroundColor: colours }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: "right", labels: { boxWidth: 10, font: { size: 10 } } },
        },
      },
    });
    return () => { if (chartRef.current) chartRef.current.destroy(); };
  }, [data, labels, colours]);

  return (
    <div style={{ height: 140 }}>
      <canvas ref={canvasRef} id={id} />
    </div>
  );
}

export default function EPCSummary({ lsoaId }) {
  const [data, setData] = React.useState(null);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState(null);

  useEffect(() => {
    if (!lsoaId) return;
    setLoading(true);
    setError(null);
    fetch(`${PBCC_DATA}/epc_dom/v3/${encodeURIComponent(lsoaId)}.json`)
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then((json) => { setData(json[0] || json); setLoading(false); })
      .catch((err) => { setError(err.message); setLoading(false); });
  }, [lsoaId]);

  if (loading) return <span className="muted">Loading EPC data...</span>;
  if (error) return <span className="muted">EPC data unavailable</span>;
  if (!data) return <span className="muted">Click a neighbourhood zone to view EPC summary</span>;

  return (
    <div className="epc-summary">
      <div className="epc-section">
        <div className="section-label">EPC Ratings</div>
        <PieChart id="epc-rating"
          data={[data.epc_A, data.epc_B, data.epc_C, data.epc_D, data.epc_E, data.epc_F, data.epc_G]}
          labels={["A", "B", "C", "D", "E", "F", "G"]}
          colours={["#0e7e58", "#2aa45b", "#8cbc42", "#f6cc15", "#f2a867", "#f17e23", "#e31d3e"]}
        />
      </div>
      <div className="epc-section">
        <div className="section-label">Building Type</div>
        <PieChart id="epc-btype"
          data={[data.type_house_detached, data.type_house_semi, data.type_house_midterrace,
                 data.type_house_endterrace, data.type_flat, data.type_bungalow_detached,
                 data.type_maisonette, data.type_parkhome]}
          labels={["Detached", "Semi", "Mid-terr", "End-terr", "Flat", "Bungalow", "Maisonette", "Park"]}
          colours={["#c2e699", "#78c679", "#31a354", "#006837", "#e31a1c", "#fbb4b9", "#1f78b4", "#fa7c00"]}
        />
      </div>
      <div className="epc-grid">
        <div className="epc-section">
          <div className="section-label">Walls</div>
          <PieChart id="epc-walls"
            data={[data.wall_verygood, data.wall_good, data.wall_average, data.wall_poor, data.wall_verypoor]}
            labels={["V.Good", "Good", "Avg", "Poor", "V.Poor"]}
            colours={["#2c7bb6", "#abd9e9", "#ffffbf", "#fdae61", "#d7191c"]}
          />
        </div>
        <div className="epc-section">
          <div className="section-label">Roof</div>
          <PieChart id="epc-roof"
            data={[data.roof_verygood, data.roof_good, data.roof_average, data.roof_poor, data.roof_verypoor]}
            labels={["V.Good", "Good", "Avg", "Poor", "V.Poor"]}
            colours={["#2c7bb6", "#abd9e9", "#ffffbf", "#fdae61", "#d7191c"]}
          />
        </div>
        <div className="epc-section">
          <div className="section-label">Heating</div>
          <PieChart id="epc-heat"
            data={[data.mainheat_verygood, data.mainheat_good, data.mainheat_average, data.mainheat_poor, data.mainheat_verypoor]}
            labels={["V.Good", "Good", "Avg", "Poor", "V.Poor"]}
            colours={["#2c7bb6", "#abd9e9", "#ffffbf", "#fdae61", "#d7191c"]}
          />
        </div>
        <div className="epc-section">
          <div className="section-label">Windows</div>
          <PieChart id="epc-wind"
            data={[data.window_verygood, data.window_good, data.window_average, data.window_poor, data.window_verypoor]}
            labels={["V.Good", "Good", "Avg", "Poor", "V.Poor"]}
            colours={["#2c7bb6", "#abd9e9", "#ffffbf", "#fdae61", "#d7191c"]}
          />
        </div>
      </div>
      <div className="epc-grid">
        <div className="epc-section">
          <div className="section-label">Main Fuel</div>
          <PieChart id="epc-fuel"
            data={[data.mainfuel_mainsgas, data.mainfuel_electric, data.mainfuel_oil, data.mainfuel_lpg, data.mainfuel_biomass]}
            labels={["Gas", "Electric", "Oil", "LPG", "Biomass"]}
            colours={["#e41a1c", "#377eb8", "#4daf4a", "#ff7f00", "#ffff33"]}
          />
        </div>
        <div className="epc-section">
          <div className="section-label">Solar PV</div>
          <PieChart id="epc-pv"
            data={[data.solarpv_yes, data.solarpv_no]}
            labels={["Yes", "No"]}
            colours={["#2c7bb6", "#d7191c"]}
          />
        </div>
      </div>
    </div>
  );
}
