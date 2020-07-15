#!/usr/bin/python3.6

import collections
from mip import *
#from graph import *
from typing import List

def addUserConstraint(m, mods_p, formator):
  # [constraint] DDR location constraint
  for v, mod_p in mods_p.items():
    if (v.name in formator.DDR_loc_2d_x):
      print(f'[AssignSLR] user specified module {v.name} to be in X {formator.DDR_loc_2d_x[v.name]}')
      m += mod_p['X'] == formator.DDR_loc_2d_x[v.name]
    if (v.name in formator.DDR_loc_2d_y):
      print(f'[AssignSLR] user specified module {v.name} to be in Y {formator.DDR_loc_2d_y[v.name]}')
      m += mod_p['Y'] == formator.DDR_loc_2d_y[v.name]
  
  # assert that user specified modules are valid
  for mod in formator.DDR_loc_2d_x.keys():
    if not any(v.name == mod for v in mods_p.keys()):
      print(f'[AssignSLR] CRITICAL WARNING: user specified module {mod} does not exist')
      exit()
  for mod in formator.DDR_loc_2d_y.keys():
    if not any(v.name == mod for v in mods_p.keys()):
      print(f'[AssignSLR] CRITICAL WARNING: user specified module {mod} does not exist')
      exit()

#
# Multi-column SLR assignment problem
#
def assignSLR(vertices : List, edges : List, formator):

  column = formator.column
  SLR_CNT = formator.SLR_CNT

  # initialize model
  m = Model()

  # [var] if a module belongs to an SLR
  # FIXME: when there are modules of the same name there will be bug
  mods_x = {} # str -> [mip_var]
  for i, v in enumerate(vertices):
    new_mod_x = [ [m.add_var(var_type=BINARY, name=f'{v.name}_{i}_x_{y}_{x}') for x in range(column[y]) ]  for y in range(SLR_CNT)] 
    mods_x[v.name] = new_mod_x # m[y][x] *** first index the y dimension

  # [var] the location of a module
  mods_p = {} # Vertex -> mip_var
  for i, v in enumerate(vertices): 
    new_mod_p = {'Y' : m.add_var(var_type=INTEGER, name=f'{v.name}_{i}_p_y'), 'X' : m.add_var(var_type=INTEGER, name=f'{v.name}_{i}_p_x') }
    mods_p[v] = new_mod_p
  
  # [var] distance of each edge
  d_x = [m.add_var(var_type=INTEGER, name=f'd_x_{e.name}_{i}') for i, e in enumerate(edges)]
  d_y = [m.add_var(var_type=INTEGER, name=f'd_y_{e.name}_{i}') for i, e in enumerate(edges)]

  # [goal] 
  m.objective = minimize(xsum(d_x[i] * edge.width for i, edge in enumerate(edges) ) + \
                         xsum(d_y[i] * edge.width for i, edge in enumerate(edges) )  )

  # [constraint] only assign to 1 SLR
  for mod_x in mods_x.values():
    m += xsum(mod_x[y][x] for y in range(SLR_CNT) for x in range(column[y]) )  == 1

  # [constraint] auxiliary varaible p
  # |   R0  |
  # |-------|  [obsolete]
  # | R1|R2 |
  # |-------|
  # the x coordinates of R1 and R2 are 0 and 2 respectively
  # the x of R0 is ** 1 ** so that it is of equatal distance to all other regions 
  # the y coordinates of R0 - R2 is 2, 0, 0 correspondingly.
  # we can apply some weights if we prefer h/v crossing
  for mod_x, mod_p in zip(mods_x.values(), mods_p.values()):
    m += mod_p['X'] == xsum(mod_x[y][x] * x for y in range(SLR_CNT) for x in range(column[y]) )
    m += mod_p['Y'] == xsum(mod_x[y][x] * y for y in range(SLR_CNT) for x in range(column[y]) )

  # [constraint] auxiliary variable d
  for d_x_i, d_y_i, e in zip(d_x, d_y, edges):
    if (e.width < formator.max_width_threshold):
      m += d_x_i >= (mods_p[e.src]['X'] - mods_p[e.dst]['X']) * e.width * formator.horizontal_cross_weight
      m += d_x_i >= (mods_p[e.dst]['X'] - mods_p[e.src]['X']) * e.width * formator.horizontal_cross_weight
      m += d_y_i >= (mods_p[e.src]['Y'] - mods_p[e.dst]['Y']) * e.width
      m += d_y_i >= (mods_p[e.dst]['Y'] - mods_p[e.src]['Y']) * e.width

  # [constraint] edges too wide should not be split
  for d_x_i, d_y_i, e in zip(d_x, d_y, edges):
    if (e.width > formator.max_width_threshold):
      m += mods_p[e.src]['X'] == mods_p[e.dst]['X']
      m += mods_p[e.src]['Y'] == mods_p[e.dst]['Y']

  # [constraint] area
  for item in ['BRAM', 'DSP', 'FF', 'LUT']:
    for y in range(SLR_CNT):
      for x in range(column[y]):
        cmd = 'm += 0'
        for v in vertices:
          cmd += f' + mods_x["{v.name}"][{y}][{x}] * {getattr(v.area, item)}'
        cmd += f'<= {int(formator.SLR_AREA[item][x] * formator.max_usage_ratio_2d[y][x])}, "{item}_SLR_{y}_sub_{x}_of_{column[y]}"'
        exec(cmd)

  addUserConstraint(m, mods_p, formator)

  # run
  m.write('assignment.lp')
  m.optimize(max_seconds=formator.max_search_time)

  writeBackAssignResult(vertices, edges, formator, mods_p)

  showAssignResult(vertices, edges, formator)

###############################################################################

def writeBackAssignResult(vertices : List, edges : List, formator, mods_p):
  for v in vertices:
    v.slr_loc = int( mods_p[v]['Y'].x)
    v.slr_sub_loc = int( mods_p[v]['X'].x)

  for e in edges:
    e.mark = mods_p[e.src]['X'].x != mods_p[e.dst]['X'].x or mods_p[e.src]['Y'].x != mods_p[e.dst]['Y'].x

  for e in edges:
    if (e.mark):
      step_v = abs(e.src.slr_loc - e.dst.slr_loc)
      step_h = abs(e.src.slr_sub_loc - e.dst.slr_sub_loc)
      e.latency = int( formator.relay_station_count(step_v + step_h) )

def showAssignResult(vertices : List, edges : List, formator):
  column = formator.column
  SLR_CNT = formator.SLR_CNT

  for y in range(SLR_CNT):
    for x in range(column[y]):
      all = []

      if (column[y] == 2):
        print(f'SLR_[{y}] part {x} includes:\n')        
        for v in vertices:
          if (v.slr_sub_loc == x and v.slr_loc == y):
            print(f'  {v.name} -> {v.area}')
            all.append(v.area)

      elif (column[y] == 1):
        print(f'SLR_[{y}] as a whole includes:\n')
        for v in vertices:
          if (v.slr_sub_loc == 0.5 and v.slr_loc == y):
            print(f'  {v.name} -> {v.area}')
            all.append(v.area)
        
      print(f'\n    BRAM usage: {sum(int(v[0]) for v in all)} / {formator.SLR_AREA["BRAM"][x]} = { (sum(int(v[0]) for v in all)) / (formator.SLR_AREA["BRAM"][x]) }')
      print(f'    DSP usage: {sum(int(v[1]) for v in all)} / {formator.SLR_AREA["DSP"][x]} = { (sum(int(v[1]) for v in all)) / (formator.SLR_AREA["DSP"][x]) }')
      print(f'    FF usage: {sum(int(v[2]) for v in all)} / {formator.SLR_AREA["FF"][x]} = { (sum(int(v[2]) for v in all)) / (formator.SLR_AREA["FF"][x]) }')
      print(f'    LUT usage: {sum(int(v[3]) for v in all)} / {formator.SLR_AREA["LUT"][x]} = { (sum(int(v[3]) for v in all)) / (formator.SLR_AREA["LUT"][x]) }\n')


  for e in edges:
    if (e.mark):
      print(f'{e.name}: {e.src.name} @ {e.src.slr_loc, e.src.slr_sub_loc} --> {e.dst.name} @ {e.dst.slr_loc, e.dst.slr_sub_loc} ')

def reBalance(vertices : List, edges_dict : Dict, formator):
  m = Model()

  edges = edges_dict.values()

  mods_S = {} # Vertex -> mip_var
  for v in vertices:
    for sub_v in v.sub_vertices.values(): 
      new_mod_S = m.add_var(var_type=INTEGER, name=f'{sub_v.name}_S')
      mods_S[sub_v] = new_mod_S  

  for e in edges:
    if ('Mem' in e.dst.name or 'Mem' in e.src.name or \
        'Router' in e.dst.name or 'Router' in e.src.name):
      print(f'[reBalance] FIXME need to handle async_mmap')
      continue
    # if at either side the edge is not accessed in pipeline, then no worries
    if (e.name in e.dst.actual_to_sub and e.name in e.src.actual_to_sub):
      src_sub = e.src.actual_to_sub[e.name]
      dst_sub = e.dst.actual_to_sub[e.name]
      adjusted_lat = e.latency if e.latency > 1 else 0
      m += mods_S[src_sub] >= mods_S[dst_sub] + adjusted_lat

  goal = 'm.objective = minimize( 0 '
  for e in edges:
    if ('Mem' in e.dst.name or 'Mem' in e.src.name or \
        'Router' in e.dst.name or 'Router' in e.src.name):
      print(f'[reBalance] FIXME need to handle async_mmap')
      continue
    if (e.name in e.dst.actual_to_sub and e.name in e.src.actual_to_sub):
      src_sub = e.src.actual_to_sub[e.name]
      dst_sub = e.dst.actual_to_sub[e.name]
      adjusted_lat = e.latency if e.latency > 1 else 0      
      goal += f' + {e.width} * (mods_S[edges_dict["{e.name}"].src.actual_to_sub["{e.name}"]] - mods_S[edges_dict["{e.name}"].dst.actual_to_sub["{e.name}"]] - {adjusted_lat})'
  goal += ')'
  
  if (goal == 'm.objective = minimize( 0 )'):
    print(f'[rebalance] WARNING: do not detect any reconvergent paths')
    return
    
  exec(goal)

  m.write('rebalance.lp')
  m.optimize(max_seconds=120)

  ##############################

  for e in edges:
    if ('Mem' in e.dst.name or 'Mem' in e.src.name or \
        'Router' in e.dst.name or 'Router' in e.src.name):
      print(f'[reBalance] FIXME need to handle async_mmap')
      continue    
    # if at either side the edge is not accessed in pipeline, then no worries
    if (e.name in e.dst.actual_to_sub and e.name in e.src.actual_to_sub):
      src_sub = e.src.actual_to_sub[e.name]
      dst_sub = e.dst.actual_to_sub[e.name]
      adjusted_lat = e.latency if e.latency > 1 else 0

      e.additional_depth = mods_S[src_sub].x - mods_S[dst_sub].x - adjusted_lat
      if (e.additional_depth):
        print(f'[reBalance] edge {e.name} is increased by {e.additional_depth}')

# treat all ports of a module as synchronized
def reBalanceNaive(vertices : List, edges_dict : Dict, formator):
  m = Model()

  edges = edges_dict.values()

  mods_S = {} # Vertex -> mip_var
  for v in vertices:
    new_mod_S = m.add_var(var_type=INTEGER, name=f'{v.name}_S')
    mods_S[v] = new_mod_S  

  for e in edges:
    adjusted_lat = e.latency if e.latency > 1 else 0
    m += mods_S[e.src] >= mods_S[e.dst] + adjusted_lat

  goal = 'm.objective = minimize( 0 '
  for e in edges:
    adjusted_lat = e.latency if e.latency > 1 else 0      
    goal += f' + {e.width} * (mods_S[edges_dict["{e.name}"].src] - mods_S[edges_dict["{e.name}"].dst] - {adjusted_lat})'
  goal += ')'
  
  if (goal == 'm.objective = minimize( 0 )'):
    print(f'[rebalance] WARNING: do not detect any reconvergent paths')
    return
    
  exec(goal)

  m.write('rebalance.lp')
  m.optimize(max_seconds=120)

  ##############################

  for e in edges:
    adjusted_lat = e.latency if e.latency > 1 else 0

    e.additional_depth = mods_S[e.src].x - mods_S[e.dst].x - adjusted_lat
    if (e.additional_depth):
      print(f'[reBalanceNaive] edge {e.name} is increased by {e.additional_depth}')
