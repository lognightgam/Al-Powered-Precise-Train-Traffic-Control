from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import time, threading

app = Flask(__name__, static_folder='frontend', static_url_path='')
CORS(app)

# --- System State ---
system_state = {
    "trains": {},
    "signals": {},
    "tracks": {"lengths": {0: 100, 1: 100, 2: 100}},
    "junctions": {},
    "ai_log": [],
    "kpis": {"punctuality": 99.1, "avg_delay": 1.2, "total_trains": 150, "delayed_trains": 5}
}
state_lock = threading.Lock()

# --- Initial System Configuration ---
def setup_initial_state():
    with state_lock:
        system_state["trains"] = {
            "T123": {"track": 0, "position": 10, "speed": 80, "status": "On Time", "priority": 1, "last_update": time.time()},
            "T456": {"track": 1, "position": 40, "speed": 70, "status": "On Time", "priority": 2, "last_update": time.time()},
            "T789": {"track": 2, "position": 80, "speed": 90, "status": "On Time", "priority": 1, "last_update": time.time()},
            "T246": {"track": 1, "position": 95, "speed": 85, "status": "On Time", "priority": 3, "last_update": time.time()},
        }
        system_state["signals"] = {
            "S1": {"track": 0, "position": 25, "state": "GREEN"},
            "S2": {"track": 0, "position": 75, "state": "GREEN"},
            "S3": {"track": 1, "position": 25, "state": "GREEN"},
            "S4": {"track": 1, "position": 75, "state": "GREEN"},
            "S5": {"track": 2, "position": 25, "state": "GREEN"},
            "S6": {"track": 2, "position": 75, "state": "GREEN"},
        }
        system_state["junctions"] = {
            "J1": {"tracks": [0, 1], "position": 50, "controlled_by": ["S2", "S4"]}
        }
        system_state["ai_log"] = [
            {"timestamp": time.time(), "level": "INFO", "message": "System initialized. AI engine is active."}
        ]

def log_ai_decision(level, message):
    entry = {"timestamp": time.time(), "level": level, "message": message}
    system_state["ai_log"].insert(0, entry)
    if len(system_state["ai_log"]) > 100:
        system_state["ai_log"].pop()

# --- AI Simulation Thread ---
def ai_simulation_thread():
    while True:
        with state_lock:
            for train_id, data in system_state["trains"].items():
                elapsed = time.time() - data["last_update"]
                clear_to_proceed = True
                for sig_id, sig_data in system_state["signals"].items():
                    if sig_data["track"] == data["track"] and sig_data["position"] > data["position"]:
                        if (sig_data["position"] - data["position"]) < 5 and sig_data["state"] != "GREEN":
                            clear_to_proceed = False
                            data["status"] = f"Waiting at signal {sig_id}"
                            break
                if clear_to_proceed:
                    distance = (data["speed"] * (elapsed / 3600))
                    data["position"] += distance
                    data["status"] = "On Time"
                data["last_update"] = time.time()
                if data["position"] >= system_state["tracks"]["lengths"][data["track"]]:
                    log_ai_decision("INFO", f"Train {train_id} has completed its journey on track {data['track']+1}.")
                    data["position"] = 0

            # Manage signals
            for sig in system_state["signals"].values():
                sig["state"] = "RED"
            for sig_id, sig_data in system_state["signals"].items():
                path_clear = True
                for train_id, train_data in system_state["trains"].items():
                    if train_data["track"] == sig_data["track"]:
                        if sig_data["position"] < train_data["position"] < sig_data["position"] + 20:
                            path_clear = False
                            log_ai_decision("ACTION", f"Path not clear for signal {sig_id}. Train {train_id} in block.")
                            break
                if path_clear:
                    sig_data["state"] = "GREEN"

            # Junction conflicts
            j1 = system_state["junctions"]["J1"]
            trains_near_j1 = [(tid, tdata) for tid, tdata in system_state["trains"].items()
                              if tdata["track"] in j1["tracks"] and abs(tdata["position"] - j1["position"]) < 25]
            if len(trains_near_j1) > 1:
                trains_near_j1.sort(key=lambda x: x[1]['priority'])
                winner_id, winner_data = trains_near_j1[0]
                log_ai_decision("WARNING", f"Conflict near Junction J1. Prioritizing {winner_id}.")
                for tid, tdata in trains_near_j1:
                    for sid, sdata in system_state["signals"].items():
                        if sdata["track"] == tdata["track"] and abs(sdata["position"] - j1["position"]) < 25:
                            sdata["state"] = "GREEN" if tid == winner_id else "RED"
                            if tid != winner_id:
                                log_ai_decision("ACTION", f"Setting signal {sid} to RED for train {tid}.")
        time.sleep(1)

# --- API Endpoints ---
@app.route('/api/state', methods=['GET'])
def get_system_state():
    since_timestamp = request.args.get('since', 0, type=float)
    with state_lock:
        recent_logs = [log for log in system_state["ai_log"] if log["timestamp"] > since_timestamp]
        response = {
            "trains": list(system_state["trains"].values()),
            "signals": system_state["signals"],
            "logs": recent_logs,
            "kpis": system_state["kpis"]
        }
    for i, train_id in enumerate(system_state["trains"].keys()):
        if i < len(response["trains"]):
            response["trains"][i]["id"] = train_id
    return jsonify(response)

@app.route('/api/simulate', methods=['POST'])
def simulate_scenario():
    data = request.json
    event_type = data.get('event_type')
    scenario, plan, impact = "Unknown", [], "Analysis in progress..."
    if event_type == 'delay':
        train_id, delay = data.get('train_id'), data.get('delay')
        scenario = f"Train {train_id} is delayed by {delay} minutes."
        plan = [
            f"Adjust signals for all crossing trains.",
            f"Prioritize holding lower-priority trains if conflicting with {train_id}.",
            f"Re-route {train_id} if track becomes congested."
        ]
        impact = "Minor cascading delays expected on 2-3 trains."
    elif event_type == 'track_closure':
        track_id, duration = data.get('track_id'), data.get('duration')
        scenario = f"Track {track_id+1} closed for {duration} minutes."
        plan = [
            f"Set all signals on Track {track_id+1} to RED.",
            f"Re-route approaching trains via junctions.",
            f"Hold trains currently on this track at nearest signal."
        ]
        impact = "Significant delays expected on this track."
    elif event_type == 'new_train':
        train_id, track_id = data.get('train_id'), data.get('track_id')
        scenario = f"Add unscheduled train {train_id} on Track {track_id+1}."
        plan = [
            f"Analyze current traffic to find safe insertion window.",
            f"Adjust signals to create gap for {train_id}.",
            f"Adjust schedule for 2-4 other trains on same track."
        ]
        impact = "Minimal impact if traffic is light."
    return jsonify({"scenario": scenario, "plan": plan, "impact": impact})

# Serve frontend
@app.route('/')
def serve_frontend():
    return send_from_directory(app.static_folder, 'index.html')

if __name__ == '__main__':
    setup_initial_state()
    threading.Thread(target=ai_simulation_thread, daemon=True).start()
    app.run(debug=True, use_reloader=False)
