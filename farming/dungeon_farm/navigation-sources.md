# 寻路源码核对与复用

- 实际依赖：https://github.com/brean/python-pathfinding ，PyPI `pathfinding==1.0.23`，MIT。直接调用 `Grid`、`AStarFinder`、`DiagonalMovement.only_when_no_obstacle`；不再自行实现 A* 搜索核心。包中保留上游许可证。
- https://github.com/xiedeming/py-yolo-dnf/blob/main/src/decision/path_planner.py ：源码明确是选择房间方向，不是房内沿走廊的完整图搜索；其 stuck_handler.py 使用移动时检测卡住与分级恢复。只作核对参考，未运行它的主程序。
- https://github.com/GuJun1990/DNF/blob/master/Map.cpp ：Dijkstra 搜索的是房间邻接图；不能解决本次房间内门柱/岩石碰撞。未运行其程序、未复制注入代码。

本机适配代码负责：读取验证过的角色坐标，将确实移动失败的位置记录为障碍网格；将 A* 路点转换成方向键。地图内容仍须由客户端数据或实际移动观测提供；开源算法本身不包含本服溶岩穴的障碍地图。
