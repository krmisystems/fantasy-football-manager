"""Check starter coverage against the remaining draft pool and position caps."""

from collections import Counter, deque

from .models import LeagueSnapshot


def roster_can_complete(snapshot: LeagueSnapshot, roster_ids: list[str]) -> bool:
    """Return whether the proposed roster can still fill every starter slot.

    Existing players cost zero selections. Each future player costs one selection.
    Position caps count primary positions. Starter slots use player eligibility.
    This structural check does not predict opponent picks or player availability.
    """
    players = {player.id: player for player in snapshot.players}
    roster = set(roster_ids)
    if len(roster) != len(roster_ids) or roster - players.keys():
        return False
    remaining_picks = snapshot.rules.roster_size - len(roster)
    if remaining_picks < 0:
        return False
    elsewhere = {pid for team in snapshot.teams if team.id != snapshot.team_id
                 for pid in team.roster_ids + team.reserve_ids}
    if roster.intersection(elsewhere):
        return False
    counts = Counter(players[pid].position for pid in roster)
    if any(count > snapshot.rules.caps.get(position, 0) for position, count in counts.items()):
        return False
    slots = list(snapshot.rules.lineup_slots().values())
    if not slots:
        return True
    owned = {pid for team in snapshot.teams for pid in team.roster_ids + team.reserve_ids}
    unavailable_ids = owned | roster | {pick.player_id for pick in snapshot.picks}

    # Each residual edge stores destination, reverse index, capacity, and cost.
    graph = [[], []]
    source, sink = 0, 1

    def node():
        graph.append([])
        return len(graph) - 1

    def edge(start, end, capacity, cost=0):
        graph[start].append([end, len(graph[end]), capacity, cost])
        graph[end].append([start, len(graph[start]) - 1, 0, -cost])

    slot_nodes = [node() for _ in slots]
    for slot_node in slot_nodes:
        edge(slot_node, sink, 1)
    position_nodes = {}
    for position, cap in snapshot.rules.caps.items():
        capacity = cap - counts[position]
        if capacity > 0:
            position_nodes[position] = node()
            edge(source, position_nodes[position], capacity)
    for player in snapshot.players:
        existing = player.id in roster
        if not existing and (player.id in unavailable_ids or player.position not in position_nodes):
            continue
        eligible = [slot_node for slot_node, positions in zip(slot_nodes, slots)
                    if set(player.eligible_positions).intersection(positions)]
        if not eligible:
            continue
        player_node = node()
        if existing:
            edge(source, player_node, 1)
        else:
            edge(position_nodes[player.position], player_node, 1, 1)
        for slot_node in eligible:
            edge(player_node, slot_node, 1)

    # Successive shortest paths support reassignment through reverse edges.
    total_cost = 0
    for _ in slots:
        distances = [float("inf")] * len(graph)
        predecessor = [None] * len(graph)
        queued = [False] * len(graph)
        distances[source] = 0
        queue = deque([source])
        queued[source] = True
        while queue:
            current = queue.popleft()
            queued[current] = False
            for index, (target, _, capacity, cost) in enumerate(graph[current]):
                if capacity and distances[current] + cost < distances[target]:
                    distances[target] = distances[current] + cost
                    predecessor[target] = (current, index)
                    if not queued[target]:
                        queued[target] = True
                        queue.append(target)
        if predecessor[sink] is None:
            return False
        current = sink
        while current != source:
            previous, index = predecessor[current]
            residual = graph[previous][index]
            residual[2] -= 1
            graph[current][residual[1]][2] += 1
            current = previous
        total_cost += distances[sink]
    return total_cost <= remaining_picks
