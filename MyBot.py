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


random.seed(0)

FULL = 700
EMPTY = 50

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
MIN_DISTANCE = 4


def get_ships(game):
    return game.me.get_ships()

def get_position_shipyard(game):
    return game.me.shipyard.position


def get_position_dropoff(game):
    return [dropoff.position for dropoff in game.me.get_dropoffs()]


def get_game_map_cells(game):
    return game.game_map.cells


def get_cell_halite(cell):
    return cell.halite_amount


def get_cell_pos(cell):
    return cell.position


def get_enemy_ships(game):
    s = []
    for i, p in game.players.items():
        if i != game.my_id:
            for ship in p.get_ships():
                s.append(ship)
    return s

def get_halite_around(game, position, radius):
    t = 0
    for x in range(-radius, radius + 1):
        for y in range(-radius, radius + 1):
            if abs(x) + abs(y) <= radius:
                t += game.game_map[Position(position.x + x, position.y + y)].halite_amount / (4 * (abs(x) + abs(y) + 1))
    return t

def is_too_close_to_enemy(game, position):
    for i, p in game.players.items():
        if i != game.my_id:
            if game.game_map.calculate_distance(position, p.shipyard.position) < MIN_DISTANCE:
                return True
            for do in p.get_dropoffs():
                if game.game_map.calculate_distance(position, do.position) < 2:
                    return True 
    return False

def get_move_cost(game, position):
    return (game.game_map[position].halite_amount / constants.MAX_HALITE) * TIME_TO_HALITE_RATIO

def has_enemy(game, position):
    cell = game.game_map[position]
    return cell.ship and cell.ship.owner != game.my_id

def is_shipyard_or_dropoff(game, position):
    cell = game.game_map[position]
    return cell.structure and cell.structure.owner == game.my_id

def closest_dropoff(ship, game):

    dropoffs = get_position_dropoff(game)

    closest_dropoff = [1000, None]

    for dropoff in dropoffs:

        distance = game.game_map.calculate_distance(ship.position, dropoff.position)

        if distance < closest_dropoff[0]:

            closest_dropoff = dropoff

    return closest_dropoff

def go_dropoff(ship, game, commands):

    target = closest_dropoff(ship, game)

    if not target[1]:

        target = get_position_shipyard(game)
    
    else: 

        target = target[1].position

    movement = get_movement(ship.position, target)

    commands.append(ship.move(movement))

def get_movement(position1, position2):

    if position1.x > position2.x:
        return Direction.West
    elif position1.x < position2.x:
        return Direction.East
    elif position1.x == position2.x:
        if position1.y > position2.y:
            return Direction.North
        elif position1.y < position2.y:
            return Direction.South

    


def look_best_cell(ship, game, range_look):
    maximum_halite = 100
    target = None

    for x in range(0,range_look):

        for y in range(0,range_look):
    
            cell_pos_x = ship.position.x + x
            cell_pos_y = ship.position.y + y

            if game.game_map[Position(cell_pos_x, cell_pos_y)].halite_amount > maximum_halite and Position(cell_pos_x, cell_pos_y) != get_position_shipyard(game):
    
                maximum_halite = game.game_map[Position(cell_pos_x, cell_pos_y)].halite_amount 
                target = game.game_map[Position(cell_pos_x, cell_pos_y)]

    logging.info(target)

    return target


def get_too_close_to_enemy_base(game, position):
    for i, p in game.players.items():
        if i != game.my_id:
            if game.game_map.calculate_distance(position, p.shipyard.position) < MIN_DISTANCE:
                return True
            for do in p.get_dropoffs():
                if game.game_map.calculate_distance(position, do.position) < 2:
                    return True 
    return False

def too_close_to_ship(game,ship):
    ship_close = None

    for x in range(1,3):
        for y in range(1,3):

            cell_pos_x = ship.position.x + x
            cell_pos_y = ship.position.y + y

            for other_ship in get_enemy_ships(game):

                if game.game_map.calculate_distance(other_ship.position, Position(cell_pos_x,cell_pos_y)) < MIN_DISTANCE:

                    ship_close = other_ship

    return ship_close

    

def go_target(agent, game, commands):

    movement = get_movement(agent.ship.position, agent.target.position)

    commands.append(agent.ship.move(movement))

def on_target(agent):

    if agent.ship.position == agent.target.position:

        return True

    return False

def accomplish_mission(agent, game, commands):

    if agent.target.position not in [agent.ship.position]:

        go_target(agent, game, commands)

    else:

        commands.append(agent.ship.stay_still())

def mission_accomplished(agent, game):

    if not agent.target:

        return True

    if game.game_map[Position(agent.target.position.x, agent.target.position.y)].halite_amount < 50:

        return True

    return False


class Agent:

    def __init__(self):
        self.ship = None
        self.weights = None
        self.mission = False

        self.returning = False
        self.target = None

    def update(self, ship):
        self.ship = ship
        self.current = None 

    def get_target(self, game):

        self.target = look_best_cell(self.ship, game, 4)

class Actions:
    def __init__(self):
        self.agents = {}
        self.created = 0
    def update(self, game):
        alive = set()
        for ship in get_ships(game):
            alive.add(ship.id)
            
            if ship.id in self.agents:
                self.agents[ship.id].update(ship)
            else:
                self.agents[ship.id] = Agent()
                self.agents[ship.id].update(ship)

        for ship_id in list(self.agents.keys()):
            if ship_id not in alive:
                del self.agents[ship_id]

    def give_ordres(self, game):
        commands = []
        if not self.agents:
            commands.append(game.me.shipyard.spawn())
            self.created = 0

        for agent in self.agents.values():

            if too_close_to_ship(game, agent.ship):

                agent.returning = True

            if agent.returning and agent.ship.halite_amount <= 50:

                agent.returning = False

            if agent.ship.halite_amount >= FULL:
                
                agent.returning = True

            if agent.returning:

                go_dropoff(agent.ship, game, commands)

            else :

                if agent.ship.position.x > get_position_shipyard(game).x + 10 or agent.ship.position.y > get_position_shipyard(game).y +10 or agent.ship.position.x > get_position_shipyard(game).x -10 or agent.ship.position.y > get_position_shipyard(game).y -10:
                    if game.me.halite_amount > 6000:
                        commands.append(agent.ship.make_dropoff())
                    pass

                if agent.mission:

                    logging.info("agent got a mission")

                    accomplish_mission(agent, game, commands)

                else:

                    agent.get_target(game)

                    agent.mission = True

                if mission_accomplished(agent, game):

                    agent.mission = False                   

        if game.me.halite_amount > 2000 and len(self.agents) < 10:
            if self.created > 5:
                commands.append(game.me.shipyard.spawn())
                self.created = 0

        self.created += 1
        return commands



game = Game()
game.ready('3 sigma')


actions = Actions()

while True:

    game.update_frame()

    actions.update(game)

    commands = actions.give_ordres(game)


    game.end_turn(commands)