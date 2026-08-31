from enum import Enum
class AgentState(str,Enum): RECEIVE='receive'; RETRIEVE='retrieve'; PLAN='plan'; ACT='act'; REFLECT='reflect'; COMPLETE='complete'; FAILED='failed'
