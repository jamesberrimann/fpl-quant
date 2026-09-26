import os
import shutil
import subprocess

import pulp

from app.models.player import Position

POSITION_REQUIREMENTS = {
    Position.GKP: 2,
    Position.DEF: 5,
    Position.MID: 5,
    Position.FWD: 3,
}

MAX_PER_TEAM = 3


class InfeasibleBudgetError(Exception):
    pass


def _resolve_cbc_path() -> str:
    try:
        prefix = subprocess.check_output(
            ["brew", "--prefix", "cbc"], stderr=subprocess.DEVNULL
        ).decode().strip()
        candidate = f"{prefix}/bin/cbc"
        if os.path.exists(candidate):
            return candidate
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    for candidate in ("/usr/bin/cbc", "/usr/local/bin/cbc"):
        if os.path.exists(candidate):
            return candidate

    return shutil.which("cbc") or "cbc"


_CBC_PATH = _resolve_cbc_path()


def optimize_squad(scored_players, budget: float = 100.0):
    prob = pulp.LpProblem("fpl_squad_selection", pulp.LpMaximize)

    player_vars = {
        player.id: prob.add_variable(f"player_{player.id}", cat="Binary")
        for player, stats, score in scored_players
    }

    prob += pulp.lpSum(
        score * player_vars[player.id] for player, stats, score in scored_players
    )

    prob += (
        pulp.lpSum(
            float(stats.price) * player_vars[player.id]
            for player, stats, score in scored_players
        )
        <= budget
    )

    for position, required_count in POSITION_REQUIREMENTS.items():
        prob += (
            pulp.lpSum(
                player_vars[player.id]
                for player, stats, score in scored_players
                if player.position == position
            )
            == required_count
        )

    teams = {player.team_id for player, stats, score in scored_players}
    for team_id in teams:
        prob += (
            pulp.lpSum(
                player_vars[player.id]
                for player, stats, score in scored_players
                if player.team_id == team_id
            )
            <= MAX_PER_TEAM
        )

    prob.solve(pulp.COIN_CMD(msg=0, path=_CBC_PATH))

    if prob.status != 1:
        raise InfeasibleBudgetError(
            f"No legal 15-player squad exists for budget £{budget}m (solver status: {prob.status})"
        )

    selected_ids = {
        player.id
        for player, stats, score in scored_players
        if player_vars[player.id].value() == 1
    }

    return [
        (player, stats, score)
        for player, stats, score in scored_players
        if player.id in selected_ids
    ]
