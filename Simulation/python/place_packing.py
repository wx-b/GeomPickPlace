#!/usr/bin/env python
'''Script for packing objects in simulation.'''

# python
import os
from time import time
# scipy
from scipy.io import savemat
from numpy.random import seed
from numpy import array, concatenate, copy, ones
import matplotlib
# self
import point_cloud
from place_packing_params import Parameters
from bonet.bonet_model import BonetModel
from geom_pick_place.pcn_model import PcnModel
from geom_pick_place.planner_packing import PlannerPacking
from geom_pick_place.planner_regrasp import PlannerRegrasp
from geom_pick_place.environment_packing import EnvironmentPacking

# uncomment when profiling
#import os; os.chdir("/home/mgualti/GeomPickPlace/Simulation")

def main():
  '''Entrypoint to the program.'''

  # PARAMETERS =====================================================================================
  
  params = Parameters()
  
  # system
  randomSeed = 0
  cwd = os.getcwd()
  deviceId = 1 if "GeomPickPlace2" in cwd else (0 if "GeomPickPlace1" in cwd else -1)
  
  # robot
  viewKeepout = 0.70
  Tsensor = array([[1, 0, 0, 0], [0, -1, 0, 0], [0, 0, -1, viewKeepout], [0, 0, 0, 1]])
  sceneWorkspace = [[0.30, 0.48], [-0.18, 0.18], [0.01, 1.00]]
  sceneViewWorkspace = [[0.00, 0.55], [-1.00, 1.00], [0.005, 1.00]]
  
  # task and environment
  cloudDirectory = "/home/mgualti/Data/GeomPickPlace/packing_clouds_test1"
  useGroundTruthSegmentation = False
  useGroundTruthCompletion = False
  useShapeCompletion = True
  nEpisodes = 200
  nObjects = 6
  
  # perception
  modelFileNameCompletion = "pcn_model_packing.h5"
  modelFileNameSegmentation = "bonet_model_packing.cptk"
  nInputPointsCompletion = 1024
  nOutputPointsCompletion = 1024
  errorThresholdCompletion = 0.006
  nInputPointsSegmentation = 2048
  scoreThreshSegmentation = 0.60
  minPointsPerSegment = params["minPointsPerSegment"]
  
  # cost factors
  taskCostFactor = params["taskCostFactor"]
  regraspPlanStepCost = params["regraspPlanStepCost"]
  segmUncertCostFactor = params["segmUncertCostFactor"]
  compUncertCostFactor = params["compUncertCostFactor"]
  graspUncertCostFactor = params["graspUncertCostFactor"]
  placeUncertCostFactor = params["placeUncertCostFactor"]
  antipodalCostFactor = params["antipodalCostFactor"]
  insignificantCost = params["insignificantCost"]
  
  # task planning
  nInitialGraspSamples = params["nInitialGraspSamples"]
  loweringDelta = params["loweringDelta"]
  collisionCubeSize = params["collisionCubeSize"]
  nWorkers = params["nWorkers"]
  maxGoalsPerWorker = params["maxGoalsPerWorker"]
  maxTaskPlanningTime = params["maxTaskPlanningTime"]
  
  # regrasp planning
  temporaryPlacePosition = params["temporaryPlacePosition"]
  nGraspSamples = params["nGraspSamples"]
  halfAngleOfGraspFrictionCone = params["halfAngleOfGraspFrictionCone"]
  nTempPlaceSamples = params["nTempPlaceSamples"]
  nGoalPlaceSamples = params["nGoalPlaceSamples"]
  maxSearchDepth = params["maxSearchDepth"]
  maxIterations = params["maxIterations"]

  # visualization/saving
  showViewer = True
  showSteps = True
  showWarnings = False
  saveFileName = "results-packing.mat"
  params = locals()
  
  # INITIALIZATION ================================================================================= 
  
  # initialize environment
  env = EnvironmentPacking(showViewer, showWarnings)
  env.RemoveFloatingHand()
  Tsensor[2, 3] += env.GetTableHeight()
  sceneWorkspace[2][0] += env.GetTableHeight()
  sceneViewWorkspace[2][0] += env.GetTableHeight()
  temporaryPlacePosition[2] = env.GetTableHeight()
  
  boxWorkspace = [(env.boxPosition[0] - env.boxExtents[0] / 2.0 + 0.01,
                   env.boxPosition[0] + env.boxExtents[0] / 2.0 - 0.01),
                  (env.boxPosition[1] - env.boxExtents[1] / 2.0 + 0.01,
                   env.boxPosition[1] + env.boxExtents[1] / 2.0 - 0.01),
                  (env.boxPosition[2] - env.boxExtents[2] / 2.0 + 0.01, 
                   Tsensor[2, 3])]
  
  # initialize model
  modelSegmentation = BonetModel(
    nInputPointsSegmentation, nObjects, deviceId, modelFileNameSegmentation)
  modelCompletion = PcnModel(nInputPointsCompletion, nOutputPointsCompletion,
    errorThresholdCompletion, deviceId, modelFileNameCompletion)
  
  # initialize planners
  taskPlanner = PlannerPacking(env, nInitialGraspSamples, loweringDelta, collisionCubeSize,
    nWorkers, maxGoalsPerWorker, maxTaskPlanningTime, minPointsPerSegment)
  regraspPlanner = PlannerRegrasp(env, temporaryPlacePosition, nGraspSamples,
    halfAngleOfGraspFrictionCone, nTempPlaceSamples, nGoalPlaceSamples, taskCostFactor,
    regraspPlanStepCost, segmUncertCostFactor, compUncertCostFactor, graspUncertCostFactor,
    placeUncertCostFactor, antipodalCostFactor, insignificantCost, maxSearchDepth, maxIterations,
    minPointsPerSegment)
  
  # RUN TEST =======================================================================================
  
  # start clock
  totalStartTime = time()  
  
  # metrics being recorded
  nPlaced = []; graspSuccess = []; graspAntipodal = []; tempPlaceStable = []; planLength = [];
  packingHeight = []; taskPlanningTime = []; regraspPlanningTime = []
  
  for episode in xrange(randomSeed, nEpisodes):
    
    # set random seed
    seed(episode)
  
    # load objects into scene
    env.LoadInitialScene(nObjects, cloudDirectory, sceneWorkspace)
    
    '''if showSteps:
      raw_input("Loaded initial scene.")'''
      
    for t in xrange(nObjects):
      
      print("Episode {}.{} ====================================".format(episode, t))
      
      # move robot out of the way
      env.MoveRobotToHome()
      env.UnplotCloud()
      env.UnplotDescriptors()
      
      # get point cloud of the scene
      env.AddSensor()
      Tsensor[0:2, 3] = point_cloud.WorkspaceCenter(sceneWorkspace)[0:2]
      env.MoveSensorToPose(Tsensor)  
      cloud = env.GetCloud(sceneViewWorkspace)
      
      if cloud.shape[0] == 0:
        print("No points in cloud of scene!")
        env.RemoveObjectNearestAnotherObject()
        continue
      
      if showSteps and cloud.shape[0] > 0:
        env.PlotCloud(cloud)
        raw_input("Acquired cloud of scene.")
        
      # get a point cloud of the box
      Tsensor[0:2, 3] = env.boxPosition[0:2]
      env.MoveSensorToPose(Tsensor)
      boxCloud = env.GetCloud(boxWorkspace)
      
      if showSteps and boxCloud.shape[0] > 0:
        env.PlotCloud(boxCloud)
        raw_input("Acquired cloud of box.")
        
      # move sensor away so it doesn't cause collisions
      env.RemoveSensor()
        
      # segment objects
      startTime = time()
      segmentedClouds, segmentationProbs, _ = taskPlanner.SegmentObjects(cloud, modelSegmentation,
        scoreThreshSegmentation, useGroundTruthSegmentation)
      print("Segmentation took {} seconds.".format(time() - startTime))
      
      if len(segmentedClouds) == 0:
        print("No segments found.")
        env.RemoveObjectNearestAnotherObject()
        continue
      
      if showSteps:
        env.PlotCloud(concatenate(segmentedClouds),
          matplotlib.cm.viridis(concatenate(segmentationProbs)))
        raw_input("Showing {} segments.".format(len(segmentedClouds)))
        
      # complete objects
      startTime = time()
      if useShapeCompletion:
        completedClouds, completionProbs = taskPlanner.CompleteObjects(\
          segmentedClouds, modelCompletion, useGroundTruthCompletion)
      else:
        completedClouds = []; completionProbs = []
        for i in xrange(len(segmentedClouds)):
          completedClouds.append(copy(segmentedClouds[i]))
          completionProbs.append(ones(segmentedClouds[i].shape[0]))
      print("Completion took {} seconds.".format(time() - startTime))
      
      if showSteps:
        env.PlotCloud(concatenate(completedClouds),
          matplotlib.cm.viridis(concatenate(completionProbs)))
        raw_input("Showing {} completions".format(len(completedClouds)))
          
      # compute normals for the target object
      normals = env.EstimateNormals(completedClouds)
          
      # get goal poses from the high level planner
      startTime = time()
      goalPoses, goalCosts, targObjIdxs = taskPlanner.GetGoalPoses(segmentedClouds,
        segmentationProbs, completedClouds, completionProbs, normals, boxCloud, regraspPlanner)
      taskPlanningTime.append(time() - startTime)
      print("Task planner completed in {} seconds.".format(taskPlanningTime[-1]))
      
      if len(goalPoses) == 0:
        print("No goal poses found.")
        env.RemoveObjectNearestAnotherObject()
        continue
      
      '''if showSteps:
        print("Showing selected object and estimated normals.")
        point_cloud.Plot(completedClouds[targObjIdx], normals[targObjIdx], 3)'''
        
      # determine obstacles for regrasp planning
      obstacleCloudsAtStart = []; obstacleCloudsAtGoal = []
      for targObjIdx in targObjIdxs:
        obstacleCloudsAtStart.append(regraspPlanner.StackClouds(completedClouds, [targObjIdx]))
        obstacleCloudsAtGoal.append(boxCloud)
        
      # get a sequence of grasp and place poses from the regrasp planner
      startTime = time()
      pickPlaces, plannedConfigs, goalIdx, targObjIdx = regraspPlanner.Plan(
        segmentedClouds, segmentationProbs, completedClouds, completionProbs, normals, goalPoses,
        goalCosts, targObjIdxs, obstacleCloudsAtStart, obstacleCloudsAtGoal)
      regraspPlanningTime.append(time() - startTime)
      print("Regrasp planner completed in {} seconds.".format(regraspPlanningTime[-1]))
      
      if len(pickPlaces) == 0:
        print("No regrasp plan found.")
        env.RemoveObjectNearestCloud(completedClouds[targObjIdx])
        continue
      
      planLength.append(len(pickPlaces))
      
      if showSteps:
        env.MoveRobotToHome()
        env.PlotDescriptors(pickPlaces)
        raw_input("Showing regrasp plan.")
      
      # actually do the pick places
      success, gSuccess, gAntipodal, tpStable  = env.ExecuteRegraspPlan( \
        pickPlaces, plannedConfigs, completedClouds[targObjIdx], showSteps)
      graspSuccess += gSuccess; graspAntipodal += gAntipodal; tempPlaceStable += tpStable
    
    # finished: evaluate and save packing result
    n, h = env.EvaluateArrangement()
    nPlaced.append(n); packingHeight.append(h)
    print("Packed {} items with height {}.".format(n, h))
    
    if showSteps:
      env.MoveRobotToHome()
      env.UnplotDescriptors()
      raw_input("End of episode.")
    
    totalTime = time() - totalStartTime
    data = {"nPlaced":nPlaced, "graspSuccess":graspSuccess, "graspAntipodal":graspAntipodal,
      "tempPlaceStable":tempPlaceStable, "planLength":planLength, "packingHeight":packingHeight,
      "taskPlanningTime":taskPlanningTime, "regraspPlanningTime":regraspPlanningTime,
      "totalTime":totalTime}
    data.update(params)
    savemat(saveFileName, data)

if __name__ == "__main__":
  main()