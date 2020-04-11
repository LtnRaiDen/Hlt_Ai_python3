#!/usr/bin/env python3
# Python 3.6

import random
import logging
import heapq
import time
from math import sqrt


from hlt.hlt_networking import Game
from hlt import hlt_constants as constants
from hlt.hlt_positionals import Direction, Position
from hlt.hlt_entity import Dropoff


# constants #########################################################

random.seed(0)

FULL = 0.975
EMPTY = 0.05

INDEX_TO_DIRECTION = {
    0: Direction.North,
    1: Direction.South,
    2: Direction.East,
    3: Direction.West,
    4: Direction.Still,
}

DIRECTION_TO_INDEX = {v: k for k, v in INDEX_TO_DIRECTION.items()}

CONSTRAIN_WEIGHT = -1.0
MIN_WEIGHT = 0.0
MAX_WEIGHT = 1.0

TIME_TO_HALITE_RATIO = 0.5

AUTO_RETURN_RATIO = 1.4
MOVE_COST_TIME = 2.7178 ** 2

STOP_BUYING_RATIO = 1.27
STOP_BUYING_RESOUCES = 0.36
SAFE_RETURN_RATIO = 1.7
HALITE_SAVED_BONUS = 1.5

DANGER_WEIGHT = 10.0

MIN_SHIPS_TO_BUY_DROPOFF = 12
RADIUS_TO_STOP = 6

CONSTANT_BUFFER = 4

OPTIMAL_DISTANCE = 14
MIN_DISTANCE = 12


# helpers ###########################################################

def look(ship, game, direction, length, opponents_in_range, danger_cost):

    length = constants.WIDTH // 3

    if get_unload_distance(ship, game) > 1:
        cell = game.game_map[ship.position.directional_offset(direction)]
        if cell.ship and cell.ship.owner != game.my_id:
            return 0

    pos = ship.position
    val = 0

    for i in range(length):
        t = 0
        for j in range(-i - 1, i + 2):
            if direction == Direction.North or direction == Direction.South:
                p = Position(pos.x + j, pos.y + (i + 1) * direction[1])
            else:
                p = Position(pos.x + (i + 1) * direction[0], pos.y + j)
            cell = game.game_map[p]
            if not (cell.ship and cell.ship.owner != game.my_id):
                if opponents_in_range[p] >= constants.INSPIRATION_SHIP_COUNT:
                    t += cell.halite_amount * constants.INSPIRED_BONUS_MULTIPLIER * HALITE_SAVED_BONUS
                else:
                    t += cell.halite_amount 
            else:
                t += 0.0
        v = t / (1 + (i + 1) * 2)
        val += (v / (i + 1)) ** 2

    cost_of_loosing_ship = ship.halite_amount / constants.MAX_HALITE

    if len(game.players) > 2:
        cost_of_loosing_ship += 1.0

    pos = ship.position.directional_offset(direction)

    danger = danger_cost[pos] * cost_of_loosing_ship if pos in danger_cost else 0

    val /= (1.0 + danger * DANGER_WEIGHT) ** 2

    return val

def weights_to_direction(weights):
    return INDEX_TO_DIRECTION[
        weights.index(max(weights))
    ]

class Map:

    def __init__(self):
        self._data = {}

    def add(self, key, value):
        if key in self._data:
            self._data[key].append(value)
        else:
            self._data[key] = [value]

    def swap(self, from_key, to_key, value):
        element = self._data[from_key]
        element.pop(element.index(value))
        self.add(to_key, value)

    def items(self):
        return list(self._data.items())


def get_unload_positions(game):
    return [
        game.me.shipyard.position
    ] + [
        dropoff.position for dropoff in game.me.get_dropoffs()
    ]

def get_unload_distance(ship, game):
    return min(game.game_map.calculate_distance(ship.position, p) for p in get_unload_positions(game))

def get_move_cost(game, position):
    return (game.game_map[position].halite_amount / constants.MAX_HALITE) * TIME_TO_HALITE_RATIO

def has_enemy(game, position):
    cell = game.game_map[position]
    return cell.ship and cell.ship.owner != game.my_id

def get_danger_cost(game, position):
    cost = 0.0
    if has_enemy(game, position):
        cost += 1.0
    for cardinal in position.get_surrounding_cardinals():
        if has_enemy(game, cardinal):
            cost += 0.25
    return cost

def get_halite_amount(game):
    total = 0
    for row in game.game_map._cells:
        for cell in row:
            total += cell.halite_amount
    return total


def is_shipyard_or_dropoff(game, position):
    cell = game.game_map[position]
    return cell.structure and cell.structure.owner == game.my_id


def get_halite_around(game, position, radius):
    t = 0
    for x in range(-radius, radius + 1):
        for y in range(-radius, radius + 1):
            if abs(x) + abs(y) <= radius:
                t += game.game_map[Position(position.x + x, position.y + y)].halite_amount / (4 * (abs(x) + abs(y) + 1))
    return t

def get_enemy_ships(game):
    s = []
    for i, p in game.players.items():
        if i != game.my_id:
            for ship in p.get_ships():
                s.append(ship)
    return s

def get_too_close_to_enemy(game, position):
    for i, p in game.players.items():
        if i != game.my_id:
            if game.game_map.calculate_distance(position, p.shipyard.position) < MIN_DISTANCE:
                return True
            for do in p.get_dropoffs():
                if game.game_map.calculate_distance(position, do.position) < 2:
                    return True 
    return False

# calculations ######################################################


class Calculations:
    '''
    to allow for caching of calculations
    '''
    def __init__(self):
        self.return_cost = {}

    def update(self):
        pass

    def calculate(self, game, curr, can_buy):
        t0 = time.time()
        self._compute_danger(game)
        logging.info(f'danger: {time.time() - t0}')
        t1 = time.time()
        self._compute_return_cost(game)
        logging.info(f'return: {time.time() - t0}')
        t2 = time.time()
        self._compute_opponents_in_radius(game)
        logging.info(f'opponents: {time.time() - t1}')
        t3 = time.time()
        if not curr and can_buy:
            self._compute_dropoff_value(game)
            logging.info(f'dropoff: {time.time() - t3}')

    def _compute_danger(self, game):
        self.danger_cost = {}

        for i, player in game.players.items():
            if i == game.my_id:
                continue
            self.danger_cost[player.shipyard.position] = 2.0
            for dropoff in player.get_dropoffs():
                self.danger_cost[dropoff.position] = 2.0

        for ship in get_enemy_ships(game):
            if ship.position in self.danger_cost:
                self.danger_cost[ship.position] += 1.0
            else:
                self.danger_cost[ship.position] = 1.0
            for p in ship.position.get_surrounding_cardinals():
                if p in self.danger_cost:
                    self.danger_cost[p] += 0.25
                else:
                    self.danger_cost[p] = 0.25

    def _compute_return_cost(self, game):
        buy_fix = len(game.me.get_ships()) - MIN_SHIPS_TO_BUY_DROPOFF

        q = [(0.0, p) if game.game_map[p].structure.id != 1337 else (10.0 - (min(4, buy_fix) * 2.5), p) for p in get_unload_positions(game)]

        seen = {}
        while q:
            cost, position = heapq.heappop(q)

            if position in seen:
                continue
            else:
                seen[position] = cost

            for destination in position.get_surrounding_cardinals():
                if destination in seen:
                    continue
                danger = self.danger_cost[destination] if destination in self.danger_cost else 0
                heapq.heappush(
                    q, 
                    (
                        cost + 1.0 + get_move_cost(game, destination) + danger * DANGER_WEIGHT, 
                        destination
                    )
                )

        min_return_cost = min(seen.values())
        max_return_cost = max(seen.values())

        self.return_cost = {k: 1.0 - (v / (max_return_cost - min_return_cost)) for k, v in seen.items()}

    def _compute_opponents_in_radius(self, game):
        self.opponents_in_range = {}
        for x in range(constants.WIDTH):
            for y in range(constants.HEIGHT):
                self.opponents_in_range[Position(x, y)] = 0

        pos = []
        for player_id, player in game.players.items():
            if player_id != game.my_id:
                for ship in player.get_ships():
                    pos.append(ship.position)

        for p in pos:
            for i in range(-4, 5):
                for j in range(-4, 5):
                    dist = abs(i) + abs(j)
                    if dist <= constants.INSPIRATION_RADIUS:
                        self.opponents_in_range[Position(p.x + i, p.y + j)] += 1

    def _compute_dropoff_value(self, game):
        dropoff_value = {}

        looking_at = []

        for x in range(constants.WIDTH):
            for y in range(constants.HEIGHT):
                p = Position(x, y)
                looking_at.append(game.game_map[p])

        looking_at = sorted(looking_at, key=lambda x: -x.halite_amount)[:int(sqrt(constants.WIDTH * constants.HEIGHT))]
        
        m = 100000

        for cell in looking_at:
            dist = get_unload_distance(cell, game)
            ene = get_too_close_to_enemy(game, cell.position)
            if dist > MIN_DISTANCE and not ene:
                t = get_halite_around(game, cell.position, 12) 
                if t // 12 > constants.MAX_HALITE // 7:
                    dropoff_value[cell.position] = t // (1 + abs(dist - OPTIMAL_DISTANCE))
                    if dist < m:
                        m = dropoff_value[cell.position]

        if m == 100000:
            self.dropoff_value = {}
            return

        min_dropoff_value = min(dropoff_value.values())
        max_dropoff_value = max(dropoff_value.values()) + 1

        self.dropoff_value = {
            k: (v / (max_dropoff_value - min_dropoff_value))for k, v in dropoff_value.items() if v == m}


# logic #############################################################

class Agent:

    def __init__(self):
        self.ship = None
        self.weights = None
        self.current = None

        self.returning = False

    def update(self, ship):
        self.ship = ship
        self.current = None 

    def calculate(self, game, calculations):
        if self.ship.halite_amount < EMPTY * constants.MAX_HALITE:
            self.returning = False
        if game.turn_number + CONSTANT_BUFFER + get_unload_distance(self.ship, game) * SAFE_RETURN_RATIO > constants.MAX_TURNS:
            self.returning = True
        if self.ship.halite_amount < game.game_map[self.ship.position].halite_amount // constants.MOVE_COST_RATIO:
            self.weights = [CONSTRAIN_WEIGHT, CONSTRAIN_WEIGHT,
                            CONSTRAIN_WEIGHT, CONSTRAIN_WEIGHT, MAX_WEIGHT]
        elif not self.returning and (self.ship.halite_amount < FULL * constants.MAX_HALITE or self.ship.halite_amount + game.game_map[self.ship.position].halite_amount // constants.EXTRACT_RATIO < constants.MAX_HALITE):
            # collect
            self.weights = self.get_weights_for_collecting(game, calculations)
        else:
            # go home
            self.returning = True
            self.weights = self.get_weights_for_returning(game, calculations)

    def get_weights_for_collecting(self, game, calculations):
        weights = [CONSTRAIN_WEIGHT] * 5
        for index, direction in enumerate(Direction.get_all_cardinals()):
            halite_to_collect = 1.0 - (self.ship.halite_amount / constants.MAX_HALITE)
            length = max(10 + int(halite_to_collect * ((min(constants.HEIGHT, constants.WIDTH) - 20) // 2)), 24)
            weights[index] = look(self.ship, game, direction, length, calculations.opponents_in_range, calculations.danger_cost)
        if not is_shipyard_or_dropoff(game, self.ship.position):
            weights[4] = (game.game_map[self.ship.position].halite_amount ** 2) * MOVE_COST_TIME
            if calculations.opponents_in_range[self.ship.position] >= constants.INSPIRATION_SHIP_COUNT:
                weights[4] *= constants.INSPIRED_BONUS_MULTIPLIER * HALITE_SAVED_BONUS
        return weights

    def get_weights_for_returning(self, game, calculations):
        weights = [MIN_WEIGHT] * 5
        for index, direction in enumerate(Direction.get_all_cardinals()):
            p = self.ship.position.directional_offset(direction)
            weights[index] = calculations.return_cost[p]
        weights[4] = calculations.return_cost[self.ship.position]
        return weights
    
    def constrain(self):
        self.weights[DIRECTION_TO_INDEX[self.current]] = CONSTRAIN_WEIGHT

    def policy(self, game):
        d = INDEX_TO_DIRECTION[
            self.weights.index(max(self.weights))
        ]
        p = self.ship.position.directional_offset(d)
        self.current = d 

        return d, p

    def is_constrainable(self, game=None):
        t = sum(1 for w in self.weights if w > CONSTRAIN_WEIGHT) > 1
        return t

    def __str__(self):
        return f'Agent({self.current})'


class Orchestrator:

    def __init__(self, game):
        self.agents = {}
        self.calculations = Calculations()
        self.total_halite = get_halite_amount(game)

    def update(self, game, curr):
        if curr:
            fake = Dropoff(game.my_id, 1337, curr)
            game.me._dropoffs[curr] = fake
            cell = game.game_map[curr]
            cell.structure = fake
        
        alive = set()
        for ship in game.me.get_ships():
            alive.add(ship.id)
            if ship.id in self.agents:
                self.agents[ship.id].update(ship)
            else:
                self.agents[ship.id] = Agent()
                self.agents[ship.id].update(ship)

        for ship_id in list(self.agents.keys()):
            if ship_id not in alive:
                del self.agents[ship_id]


    def calculate(self, game, curr, can_buy):
        t0 = time.time()
        self.calculations.calculate(game, curr, can_buy)
        logging.info(f'calc: {time.time() - t0}')
        t1 = time.time()
        for agent in self.agents.values():
            agent.calculate(game, self.calculations)
        logging.info(f'agents: {time.time() - t1}')
        self.halite_collected = 1 - (get_halite_amount(game) / self.total_halite)

    def policy(self, game, curr):
        # Shuld return orders for all the ships
        returning = game.turn_number + constants.WIDTH > constants.MAX_TURNS

        if curr:
            dist_to_dropoff = [game.game_map.calculate_distance(s.position, curr) for s in game.me.get_ships() if self.agents[s.id].returning or s.halite_amount > constants.MAX_HALITE * 0.7]
            save_more = all((
                dist_to_dropoff and RADIUS_TO_STOP > min(dist_to_dropoff),
                not game.me.halite_amount >= constants.DROPOFF_COST - game.game_map[curr].halite_amount + constants.SHIP_COST
            ))
        else:
            save_more = False

        requests = Map()

        for agent in self.agents.values():
            d, p = agent.policy(game)
            # direction 
            requests.add(p, agent)


        finnished = False
        counter = 1

        while not finnished:
            finnished = True

            for position, agents in requests.items():
                # if collide
                if len(agents) > 1 and not (returning and is_shipyard_or_dropoff(game, position)):
                    # dont
                    # should be the one with the currently worst choice
                    # try to change one of the collecting
                    constrainable = [a for a in agents if a.is_constrainable(game=game)]


                    collecting = [a for a in constrainable if not a.returning]
                    r = [a for a in constrainable if a.returning]

                    if collecting:
                        agent = min(collecting, key=lambda x: x.ship.halite_amount)
                    elif r:
                        agent = min(r, key=lambda x: x.weights[DIRECTION_TO_INDEX[x.current]])
                    else:
                        swapable = [
                            a for a in agents if agent.current != Direction.Still]
                        if swapable:
                            agent = random.choice(swapable)
                            agent.weights = [CONSTRAIN_WEIGHT, CONSTRAIN_WEIGHT,
                                            CONSTRAIN_WEIGHT, CONSTRAIN_WEIGHT, MAX_WEIGHT]
                            d, p = agent.policy(game)
                            requests.swap(position, p, agent)
                        finnished = False
                        continue


                    # stop the agent from making the decision the next call
                    agent.constrain()
                    # make a new move
                    d, p = agent.policy(game)
                    requests.swap(position, p, agent)
                    # flag that there was a conflict
                
                    finnished = False
                
            counter += 1

            if counter > 200:
                logging.error('FAILED FIXING :(')
                break

        commands = []

        for agent in self.agents.values():
            if curr and agent.ship.position == curr and game.me.halite_amount >= constants.DROPOFF_COST - game.game_map[curr].halite_amount - agent.ship.halite_amount:
                commands.append(agent.ship.make_dropoff())
                continue
            if returning and is_shipyard_or_dropoff(game, agent.ship.position):
                continue
            commands.append(agent.ship.move(agent.current))
            p = agent.ship.position.directional_offset(agent.current)
            if game.game_map[agent.ship.position].ship == agent.ship:
                game.game_map[agent.ship.position].ship = None

            game.game_map[p].mark_unsafe(agent.ship)

          
        if not save_more and (self.halite_collected < (1.0 - STOP_BUYING_RESOUCES) and game.turn_number < constants.MAX_TURNS / STOP_BUYING_RATIO) and game.me.halite_amount >= constants.SHIP_COST and not game.game_map[game.me.shipyard].is_occupied and len(game.me.get_ships()) <= 120:
            commands.append(game.me.shipyard.spawn())

        return commands

        
# usage #############################################################


game = Game()
game.ready('3 sigma')

# planned = [Position(0, 32), Position(16, 14), Position(0, 52), Position(24, 50)]
planned = []

curr = None

can_buy = False
allowed_dropoffs = ((constants.WIDTH - 32) // 8) + (1 if len(game.players.keys()) == 2 else 0)
dropoff_cooldown = 0

orchestrator = Orchestrator(game)

while True:
    game.update_frame()

    logging.info('state:')
    logging.info(f'ships -> {len(game.me.get_ships())}')

    logging.info(f'dropoffs -> {game.me.get_dropoffs()}')

    if dropoff_cooldown > 0:
        dropoff_cooldown -= 1

    if len(game.me.get_ships()) >= MIN_SHIPS_TO_BUY_DROPOFF and len(game.me.get_dropoffs()) <  allowed_dropoffs and game.turn_number < constants.MAX_TURNS - 100:
        can_buy = True
    else:
        if len(game.me.get_dropoffs()) >= allowed_dropoffs:
            can_buy = False


    if (not curr) or game.game_map[curr].structure:
        if curr and game.game_map[curr].structure.id == game.my_id:
            dropoff_cooldown = 10
        curr = None
        
    logging.info(f'curr -> {curr}')

    t0 = time.time()

    orchestrator.update(game, curr if dropoff_cooldown == 0 else None)

    t1 = time.time()

    logging.info(f'[UPDATE] t={t1 - t0}')

    orchestrator.calculate(game, curr, can_buy)

    if not curr and can_buy:
        if orchestrator.calculations.dropoff_value:
            curr = max(
                orchestrator.calculations.dropoff_value.items(), key=lambda x: x[1])[0]
        else:
            curr = None
    
    t2 = time.time()

    logging.info(f'[CALCUlATE] t={t2 - t1}')

    commands = orchestrator.policy(
        game, curr if dropoff_cooldown == 0 else None)

    t3 = time.time()

    logging.info(f'[POLICY] t={t3 - t2}')

    logging.info(f'[DONE] t={t3 - t0}')

    for row in game.game_map._cells:
        for cell in row:
            if cell.structure and cell.structure.id == 1337:
                cell.structure = None 
    
    for pos, d in list(game.me._dropoffs.items()):
        if d.id == 1337:
            del game.me._dropoffs[pos]

    game.end_turn(commands)

    # print('yolo')