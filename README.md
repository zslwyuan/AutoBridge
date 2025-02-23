# Latest

- We are in transition to our new code base in the "in-develop" directory. We hope to make the tool flexible regarding the target device, the optimization methods, which front-end HLS to use, etc. Please let me know if you have any suggestions!

# About

- `What`: AutoBridge is a floorplanning tool for Vivado HLS dataflow designs.

- `Why`: Co-optimizing HLS compilation and placement brings new opportunities to improve the final achievable frequency.

- `How`: Pre-determine the rough location of each module during HLS compilation, so that:
    * the long interconnect could be adequately pipelined by the HLS scheduler.

    * we prevent the Vivado placer to place the logic too densely.

- In our experiments with a total of 43 design configurations, we improve the average frequency from 147 MHz to 297 MHz. 

    * Notably, in 16 experiments we make the originally unroutable designs achieve 274 MHz on average
    
- The pre-print manuscript of our paper could be found at 
https://vast.cs.ucla.edu/sites/default/files/publications/AutoBridge_FPGA2021.pdf

- Projects using AutoBridge:

    * AutoSA Systolic Array Compiler (https://github.com/UCLA-VAST/AutoSA)
    * TAPA Compiler (https://github.com/Blaok/tapa)

- Motivating Examples:

   * Comparison of a stencil accelerator on Xilinx U280. From routing failure to 297 MHz.
      * Each color represents a module.
      * AutoBridge ensures a clean separation of logic in different regions to minimize unnecessary die crossing.
![][image-1]

   * Comparison of a systolic array on Xilinx U250. From 158 MHz to 316 MHz. 
      * Note that Vivado will try to pack things together to avoid die crossing as much as possible. 
      * Instead, we ensure a balanced resource utilization across the whole device to reduce local congestion.
      * Meanwhile, the global connections will be adequately pipelined.
![][image-2]


# Requirements

- Python 3.6+ and Pip
```
sudo apt install software-properties-common
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update
sudo apt install python3.6
sudo apt install python3-pip
```
- Pyverilog
```
python3.6 -m pip install pyverilog
```
- Iverilog
```
sudo apt install iverilog
```
- Python mip version 1.8.1
```
python3.6 -m pip install mip==1.8.1
```
- It is highly recommended that the user install the `Gurobi` solver which is free to academia and can be easily installed. 

  - Register and download the `Gurobi Optimizer` at https://www.gurobi.com/downloads/gurobi-optimizer-eula/
  - Unzip the package to your desired directory
  - Obtain an academic license at https://www.gurobi.com/downloads/end-user-license-agreement-academic/
  - The environment variable `GUROBI_HOME` needs to point to the installation directory, so that Gurobi can be detected by AutoBridge.
    - `export GUROBI_HOME=WHERE-YOU-INSTALL`
    - `export GRB_LICENSE_FILE=ADDRESS-OF-YOUR-LICENSE-FILE`
    - `export PATH="${PATH}:${GUROBI_HOME}/bin"`
    - `export LD_LIBRARY_PATH="${LD_LIBRARY_PATH}:${GUROBI_HOME}/lib"`

- Package for Alveo U250 and U280 FPGA
  -  https://www.xilinx.com/support/download/index.html/content/xilinx/en/downloadNav/alveo.html

  - U250: `2018.3.2` with `XDMA`
  - U280: `2019.2` with `XDMA`


- Xilinx Vivado HLS and Xilinx Vitis
   - Note that the original experiments are based on the version 2019.2. 
   - So far the floorplanner works well with designs compiled by the latest Vitis HLS 2020.2. However, Vitis HLS 2020.2 seems to have a bug in creating the "xo" object (Step 3). We are contacting Xilinx to confirm.


# Introduction

Despite an increasing adoption of high-level synthesis (HLS) for its design productivity advantages, there remains a significant gap in  the achievable clock frequency between an HLS-generated design and an optimized handcrafted RTL. In particular, the difficulty in accurately estimating the interconnect delay at the HLS level is a key factor that limits the timing quality of the HLS outputs. Unfortunately, this problem becomes even worse when large HLS designs are implemented on the latest multi-die FPGAs, where die-crossing interconnects incur a high delay penalty.

To tackle this challenge, we propose `AutoBridge`, an automated framework that couples a `coarse-grained floorplanning` step with `pipelining` during HLS compilation. 
- First, our approach provides HLS with a view on the global physical layout of the design; this allows HLS to more easily identify and pipeline the long wires, especially those crossing the die boundaries. 
- Second, by exploiting the flexibility of HLS pipelining, the  floorplanner is able to distribute the design logic across multiple dies on the FPGA device without degrading clock frequency; this avoids the aggressive logic packing on a single die, which often results in local routing contention that eventually degrades timing. 
- Since pipelining may introduce additional latency, we further present analysis and algorithms to ensure the added latency will not hurt the overall throughput. 

![][image-3]

Currently AutoBridge supports two FPGA devices: the Alveo U250 and the Alveo U280. The users could customize the tool to support other FPGA boards as well.

## Inputs

To use the tool, the user needs prepare for their  Vivado HLS project that has already been c-synthesized. 

  

To invoke AutoBridge, the following parameters should be provided by the user:

* `project_path`: Directory of the HLS project. 

* `top_name`: The name of the top-level function of the HLS design

* `DDR_enable`: A vector representing which DDR controllers the design will connect to. In U250 and U280, each SLR of the FPGA contains the IO bank for one DDR controller that can be instantiated. For example, 

```python
      DDR_enable = [1, 0, 0, 1]
``` 

means that there are four SLRs (U250) and the DDR controller on the SLR 0 and SLR 3 (the bottom one is the 0-th) are instantiated while the SLR 1 and SLR 2 are not instantiated. This parameter will affect the floorplanning step, as we must not use the area preserved for DDR controllers.

- `DDR_loc_2d_y`: A dictionary recording the y-dim location of user-specified modules. For each IO module (which will directly connect to peripheral IPs such as DMA or DDR controller) in the design, the user must explicity tell the tool which region this module should be placed, according to the location of the target peripheral IPs (which usually have fixed locations). For example, 
```python
      DDR_loc_2d_y['foo'] = 1
```  
means that the module (HLS function) **foo** must be placed in the 1-st SLR of the FPGA.

- `DDR_loc_2d_x`: A dictionary recording the x-dim location of user-specified modules. By default we split each SLR by half. For example, 
```python
      DDR_loc_2d_x['bar'] = 1
```  
means that the module (HLS function) must be placed in the right half (1 for the right half and 0 for the left half) of the FPGA.

- `max_usage_ratio_2d`: A 2-dimensional vector specifying the maximum resource utilization ratio for each region. For example, 
```python
      max_usage_ratio_2d = [ [0.85, 0.6], [0.85, 0.6], [0.85, 0.85], [0.85, 0.6] ]
```
means that there are 8 regions in total (2x4), and at most 85% of the available resource on the left half of SLR 0 can be used, 60% of the right half of SLR 0 can be used, 85% of either the right and the left half of SLR 2 can be used, etc.


## Outputs

The tool will produce:

- A new RTL file corresponding to the top HLS function that has been additionally pipelined based on the floorplanning results. 

- A `tcl` script containing the floorplanning information.

## Usage

- Step 1: compile your HLS design using Vivado HLS.

- Step 2: invoke AutoBridge to generate the floorplan file and transform the top RTL file.

- Step 3: pack the output from Vivado HLS and AutoBridge together into an `xo` file.

- Step 4: invoke Vitis for implementation.

Reference scripts for step 1, 3, 4 are provided in the `reference-scripts` folder. For step 2, we attach the AutoBridge script along with each benchmark design.

# Issues

- Should use mip version 1.8.1.

- If you encounter the situation where the `mip` package complains that `multiprocessing` cannot be found, please upgrade the `pyverilog` to the latest release. Or if you run the program a second time things may work out.

- In the divide-and-conquer approach, if a region is packed close to the max_usage_ratio, then it's possible that the next split will fail because a function cannot be split into two sub regions. The current work-around is to increase the max_usage_ratio a little bit.

- Function names in the HLS program should not contain "fifo" or "FIFO".


# FPGA'21 Artifact Review

The experiment results for all benchmarks in our submission to FPGA'21 are available at:
https://ucla.box.com/s/5hpgduqrx93t2j4kx6fflw6z15oylfhu

Currently only a subset of the source code of the benchmarks are open-sourced here, as some designs are not published yet and will be updated later.

[image-1]:	https://user-images.githubusercontent.com/32432619/104076425-e8729880-51ca-11eb-97e0-402e9b67c4e8.png
[image-2]:	https://user-images.githubusercontent.com/32432619/104076467-017b4980-51cb-11eb-8c44-f01ccf681da5.png
[image-3]:  https://user-images.githubusercontent.com/32432619/104138330-441e5c80-5358-11eb-8a7f-bc2841ee72c8.png
