CXX = g++
CXXFLAGS = -O2 -march=native -mstackrealign -ftracer -finline-functions -g -frename-registers -fbranch-target-load-optimize2 -fmodulo-sched -g0 -Wno-all -fPIC -std=gnu++0x
LDFLAGS = -fPIC -shared -Wl,-O1 -Wl,--export-dynamic 
PYTH0N_INCLUDE = /usr/include/python2.7 
LIBS = -lboost_python-2.7 -lboost_thread -lopencv_core -lopencv_videoio -lopencv_video
TARGET  = camstream

$(TARGET).so: $(TARGET).o
	g++ $(LDFLAGS) $^ $(LIBS) -o $@

$(TARGET).o: $(TARGET).cpp
	$(CXX) $(CXXFLAGS) -I $(PYTH0N_INCLUDE) -c $<

