#define NDEBUG
#include <iostream>
#include <vector>
#include <ctime>
#include <mutex>
#include <condition_variable>
#include <boost/scoped_ptr.hpp>
#include <boost/thread.hpp>
#include <boost/thread/locks.hpp>
#include <boost/thread/condition_variable.hpp>
#include <boost/python.hpp>
#include <boost/atomic.hpp>
#include <opencv2/opencv.hpp>
#include <opencv2/video.hpp>
#include <opencv2/features2d/features2d.hpp>
#include <sched.h>
#include <pthread.h>
#include <boost/lockfree/spsc_queue.hpp>



using namespace boost::python ;

//Gil release from C code.
class ScopedGILRelease {
public:
	inline ScopedGILRelease() { m_thread_state = PyEval_SaveThread(); }
	inline ~ScopedGILRelease() { PyEval_RestoreThread(m_thread_state); m_thread_state = NULL; }
private:
	PyThreadState* m_thread_state;
};

//Gil Lock
class GilLock{
public:
	inline GilLock() {this->gil = PyGILState_Ensure();}
	inline ~GilLock() {PyGILState_Release(this->gil);}
private:
	PyGILState_STATE gil;
};


//Synchronized thread with atomic
class Spinlock {
private:
  typedef enum {Locked, Unlocked} LockState;
  boost::atomic<LockState> m_state;

public:
  Spinlock() : m_state(Unlocked) {}

  void lock(){
    while (m_state.exchange(Locked, boost::memory_order_acquire) == Locked){
      boost::this_thread::yield();
    }
  }
  void unlock(){
    m_state.store(Unlocked, boost::memory_order_release);
  }
};



//Implementation PyObj
class PyObj_ptr{
public:
	PyObject* object = nullptr;
	
	PyObj_ptr(){
	};
	PyObj_ptr(PyObject* ptr){
		init(ptr);
	}
	~PyObj_ptr(){
		reset();
	}
	
	operator PyObject*(){
		return this->object;
	}
	
	PyObj_ptr& operator=(const PyObj_ptr& pyobj){
		init(pyobj.object);
		return *(this);
	}
	inline void init(PyObject* ptr){
		Py_XINCREF(ptr);
		this->object = ptr;
	}
	inline void reset(){
		std::cout << "reset" << this->object << std::endl;
		Py_XDECREF(this->object);
		this->object = nullptr;
	}
		
	inline void reset(PyObject* pyobj){
		reset();
		init(pyobj);
	}
	
	PyObject* release(){
		PyObject* p = this->object;
		reset();
		return p;
	}
	
	uint16_t refcnt(){
		if (this->object != nullptr){
			return static_cast<uint16_t>(this->object->ob_refcnt);
		}
		return 0;
	}
};



//Call python functions from thread

template<class ...Args>
inline void pyCallback(PyObject* callback,const Args&... args){
	GilLock gil = GilLock();
	if (callback!=nullptr && PyCallable_Check(callback)){
		try{
			PyObject* _self = PyMethod_Self(callback);
			if (_self == nullptr){
				boost::python::call<void>(callback, args...);
			}else{
				PyObject* func_name = PyObject_GetAttrString(
					PyObject_GetAttrString(callback, "im_func"), "func_name");
				const char*  s_name = extract<const char*>(func_name);
				boost::python::call_method<void>(_self,s_name, args...);
			}
		}catch(std::exception &e){
			std::cout << e.what() << std::endl;
		}
	}
}


std::string rect_to_st(const cv::Rect& self){
	
	std::stringstream s;
	s << "Rectangle ";
	s << "[";
	s << "x:" << self.x << ", "; 
	s << "y:" << self.y << ", ";
	s << "h:" << self.height << ", ";
	s << "w:" << self.width;
	s << "]";
	return s.str();
};


boost::python::dict rect_to_dict(const cv::Rect& self){
	boost::python::dict d;
	d["x"] = self.x;
	d["y"] = self.y;
	d["w"] = self.width;
	d["h"] = self.height;
	return d;
}


//This method high load CPU
// class MotionDetection2{
// public:
// 	cv::Rect m_crop;
// 	
// 	MotionDetection2(uint8_t iteration = 0){
// 		m_bg_mog = cv::createBackgroundSubtractorMOG2(64,16,false);
// 	}
// 	
// 	~MotionDetection2(){}
// 	
// 	void setMotionCallback(PyObject* cb){
// 		
// 	}
// 	
// 	void detect(cv::Mat* frame_orig){
// 		cv::Mat bg_mask;
// 		m_bg_mog->apply(*frame_orig, bg_mask);
// 		bg_mask.copyTo(*frame_orig);
// 		
// 	}
// private:
// 	PyObj_ptr m_callback;
// 	cv::Ptr<cv::BackgroundSubtractor> m_bg_mog;
// };


class MotionDetection{
public:
	
	cv::Rect m_crop;
	float m_sens = .1;
	PyObj_ptr m_callback;
	
	MotionDetection(uint8_t iteration = 0){
		m_erode_kernel = cv::getStructuringElement(cv::MORPH_RECT, cv::Size(3,3));
		m_th_frame = iteration;
	};
	
	~MotionDetection(){
		std::cout << "Delete MotionDetection " << this << std::endl;
// 		m_prev_detect_regions.clear();
	}
	
	void detect(cv::Mat& frame_orig){
		
		
		if (m_th_it != 0){ //skip frames while m_th_it !=0
			m_th_it--;
			for (auto const& rect : m_prev_detect_regions){
				cv::rectangle(frame_orig, rect.tl(), rect.br(),cv::Scalar(255, 255, 255));
			}
			return;
		}
		
		m_th_it = m_th_frame; // refresh m_th_it
		
		
		cv::Mat cropped_frame;
		cv::Mat* frame = &frame_orig;
		
		
		
		if (m_crop.size().area() > 1){
			frame_orig(m_crop).copyTo(cropped_frame);
			frame = &cropped_frame;
		}
		
		cv::Mat _gray_frame;
		cv::Mat _betw_diff;
		cv::cvtColor(*frame, _gray_frame, CV_RGB2GRAY);
		
		switch(this->m_step){
			case 0:
				m_step++;
				break;
			case 1:
				cv::absdiff(m_last_frame,_gray_frame,m_frame_diff1);
				m_step++;
				break;
			case 2:
				cv::absdiff(_gray_frame,m_last_frame, m_frame_diff2);
				cv::bitwise_and(m_frame_diff1,m_frame_diff2,_betw_diff);
				cv::threshold(_betw_diff, _betw_diff, 20, 255, CV_THRESH_BINARY);
// 				cv::morphologyEx(_betw_diff,_betw_diff,cv::MORPH_OPEN,m_erode_kernel);
				cv::dilate(_betw_diff, _betw_diff, m_erode_kernel, cv::Point(-1,-1) ,2);
				m_frame_diff1 = m_frame_diff2;
				m_last_frame = _gray_frame;
				
				std::vector<std::vector<cv::Point> > contours;
				
				cv::findContours( _betw_diff, contours, cv::RETR_EXTERNAL, cv::CHAIN_APPROX_SIMPLE, cv::Point(1, 1));

				
				float _frame_size = frame->cols*frame->rows;
// 				std::cout << m_crop.size().area() << std::endl;
				
				m_prev_detect_regions.clear();
				for (auto const& vect : contours ){
					cv::Rect rect = cv::boundingRect(vect);
					float _calc_area = (rect.size().area()/_frame_size)*100;
					
					rect.x += m_crop.x;
					rect.y += m_crop.y;

					if (_calc_area > 0.5){
						m_prev_detect_regions.push_back(rect);
						cv::rectangle(frame_orig, rect.tl(), rect.br(),cv::Scalar(255, 255, 255));
					}
				}
				if (m_prev_detect_regions.size() > 0){
					::pyCallback<bool>(m_callback.object,true);
				}
				
		}
		m_last_frame = _gray_frame;
		
	}
	
private:
	cv::Mat m_frame_diff1;
	cv::Mat m_frame_diff2;
	cv::Mat m_last_frame;
	cv::Mat m_erode_kernel;
	uint8_t m_step = 0;
	uint8_t m_th_frame;
	uint8_t m_th_it = 0;
	
	std::vector<cv::Rect> m_prev_detect_regions;
	
	
	
};





//Thread write video on hard drive

class VideoWriterThread{
public:
	volatile bool m_run = true;
	char* m_codec;
	
	explicit VideoWriterThread(const std::string& path, const cv::Size& size, double& fps){
		m_run = true;
		m_stream_thread.reset(new boost::thread(&VideoWriterThread::write_process,this,path, size, fps));
	}
	~VideoWriterThread(){
		m_run = false;
	}

	void stop(bool assync = true){
		m_run = false;
		cond_var.notify_one();
		if(assync){
			m_stream_thread->join();
		}
	}

	void add(cv::Mat* frame_){
		m_queue.push(frame_);
		cond_var.notify_one();
	}

private:
	boost::lockfree::spsc_queue<cv::Mat*, boost::lockfree::capacity<2>> m_queue;
	boost::scoped_ptr<boost::thread> m_stream_thread;
	std::mutex m_lock;
	std::condition_variable cond_var;
	void write_process(std::string path, cv::Size size, double fps ){
		std::cout << "start video io thread" << (this)  << std::endl;
		cv::VideoWriter video_io(path, CV_FOURCC(m_codec[0], m_codec[1], m_codec[2], m_codec[3]), fps, size, true);
		if (!video_io.isOpened()){
			std::cout << "video_io not opened " << path <<" "<< size<< " " << fps << std::endl;
			return;
		}
		std::unique_lock<std::mutex> lock(m_lock);
		while(m_run){
			cv::Mat* frame_ = nullptr;
			if(!m_queue.pop(frame_)){
				cond_var.wait(lock);
				continue;
			}
			if(frame_ != nullptr){

				video_io << (*frame_);
				delete frame_;
			}
		}
		video_io.release();
		std::cout << "stop video io thread" << (this)  << std::endl;
	}
};










//auto finalize video capture

class VideoFinalize{
public:
	cv::VideoCapture* cap_ = nullptr;
	explicit VideoFinalize(cv::VideoCapture* cap){
		cap_ = cap;
	}
	~VideoFinalize(){
		if(cap_){
			cap_->release();
		}
	}
};









// #####################################################################################
// главный класс реализующий python -> C api

class CamStream{
public:
	

	enum events {
		device_open_error,
		device_open_success,
		device_disconnect,
		unhandled_error,
		thread_start,
		thread_stop
	};
	
	CamStream():
		m_run(false){
	}
	~CamStream(){
		std::cout << "Delete" << this << "\n";
	}
	void onCaptureUpdate(PyObject* cb){
		if ( cb == Py_None){
			m_callback.reset();
		}else{
			m_callback.reset(cb);
		}
	}

	void onThreadEvent(PyObject *cb){     //set callback notify for change thread status, 
		if (cb == Py_None){               //set None for reset callback
			m_on_thread_event.reset();
		}else{
			m_on_thread_event.reset(cb);
		}
	}
			
	template<typename A>
	void start(A source){
		m_start_time = std::time(0);
		m_run = true;
		m_stream_thread.reset(new boost::thread(&CamStream::process<A>, this, source));
	}
			
	void stop(){
		ScopedGILRelease scp = ScopedGILRelease();
		this->stopAssync();
		m_stream_thread->join();}
			
	void stopAssync(){
		GilLock gil = GilLock();
		m_motion_detect.reset();
		m_run = false;}
		
// 	void enableMotinDetect(PyObject* detectCallback,cv::Rect& rect, float sens = .1){
// 		_enableDetect(detectCallback, sens, &rect);
// 	}
// 	
// 	void enableMotinDetect(PyObject* detectCallback,float sens = .1){
// 		_enableDetect(detectCallback, sens, nullptr);
// 	}
		
	void enableMotinDetect(PyObject* detectCallback,cv::Rect* rectangle,float sens = .1){
		ScopedGILRelease scp = ScopedGILRelease();
		boost::lock_guard<std::mutex> lock(m_resource_lock);
		std::cout << "Enable motion Detection" << std::endl;
		std::cout << "Set senitive " << sens << std::endl;
		m_motion_detect.reset(new MotionDetection(1)); //create shared ptr 
		
		if (rectangle != nullptr){
			m_motion_detect->m_crop = (*rectangle);
			std::cout << "Set area detection " << rectangle->size().area() <<  std::endl;
		}
  		m_motion_detect->m_callback.reset(detectCallback);               // setCallback python functions
	}
	
	bool detectorIsEnabled(){
		ScopedGILRelease scp = ScopedGILRelease();
		boost::lock_guard<std::mutex> lock(m_resource_lock);
		return m_motion_detect != nullptr;
	}
	
	void stopMotionDetect(){
		ScopedGILRelease scp = ScopedGILRelease();
		boost::lock_guard<std::mutex> lock(m_resource_lock);
		m_motion_detect.reset();
		std::cout << "Stop motion Detection" << std::endl;
	}
	
	bool isRunning(){
		if(m_stream_thread != nullptr){
			return m_stream_thread->joinable();
		}
		return false;
	}
	
	bool startRecord(std::string path,char* codec, cv::Size size = cv::Size(640,480)){
		ScopedGILRelease scp = ScopedGILRelease();
		double fps = m_camera_io.get(CV_CAP_PROP_FPS);
		boost::lock_guard<std::mutex> lock(m_resource_lock);
		if (m_video_io!=nullptr){
			return false;
		}
		VideoWriterThread* v = new VideoWriterThread(path, size, fps);
		v->m_codec=codec;
		m_video_io.reset(v);
		return true;
	}
	
	bool stopRecord(){
		ScopedGILRelease scp = ScopedGILRelease();
		boost::lock_guard<std::mutex> lock(m_resource_lock);
		if (m_video_io != nullptr){
			m_video_io->stop(false);
			m_video_io.reset();
			return false;
		}
		return true;
	}
	
	boost::python::dict getState(){
		
		ScopedGILRelease scp = ScopedGILRelease();
		boost::python::dict _data;
		
		if (isRunning()){
			_data["uptime"] = std::time(0) - m_start_time;
			_data["start_time"] = m_start_time;
			
			struct sched_param param;
			int _policy, ret;
			pthread_t threadID = (pthread_t) m_stream_thread->native_handle();
			if (ret = pthread_getschedparam(threadID, &_policy, &param) == 0){
				_data["thread_policy"] = _policy;
				std::string  sched_typ;
				switch(param.sched_priority){
					case 0:
						sched_typ = "SCHED_NORMAL";
						break;
					case 1:
						sched_typ = "SCHED_FIFO";
						break;
					case 2:
						sched_typ = "SCHED_RR";
						break;
					case 3:
						sched_typ = "SCHED_BATCH";
						break;
					case 4:
						sched_typ = "SCHED_ISO";
						break;
					case 5:
						sched_typ = "SCHED_IDLE";
						break;
					case 6:
						sched_typ = "SCHED_DEADLINE";
						break;
					default:
						sched_typ = "SCHED_";
						sched_typ+= std::to_string(param.sched_priority);
				}
				_data["thread_sched"] = param.sched_priority;
				_data["thread_sched_type"] = sched_typ;
			}else{
				_data["thread_sched"] = boost::python::object();
			}
			
			m_resource_lock.lock();
			
			if (m_motion_detect != nullptr){
				boost::python::dict _data2;
				_data2["area"] = rect_to_dict(m_motion_detect->m_crop);
				_data2["sensitivy"] = m_motion_detect->m_sens;
				_data["detector"] = _data2;
			}
			_data["record"] = (m_video_io != nullptr);
			m_resource_lock.unlock();
			
		}
		return _data;
	}
	
	bool schedule(int policy, uint8_t priority){
		ScopedGILRelease scp = ScopedGILRelease();
	// It s list of policy, look to sched.c
	// #define SCHED_NORMAL            0
	// #define SCHED_FIFO              1
	// #define SCHED_RR                2
	// #define SCHED_BATCH             3
	// #define SCHED_IDLE              5
	// #define SCHED_DEADLINE          6
			
		
		if (m_stream_thread == nullptr){
			std::cout << "thread not started" << std::endl;
			return false;
		}
		
		struct sched_param param;
		int _policy, ret;
		pthread_t threadID = (pthread_t) m_stream_thread->native_handle();
	
		if (ret = pthread_getschedparam(threadID, &_policy, &param) != 0){
			std::cout << "Can not read thread parameters " << ret << std::endl;
			return false;
		}
		std::cout << "Thread id " << threadID << std::endl;
		std::cout << "Policy " << _policy << std::endl;
		std::cout << "Priority" << param.sched_priority << std::endl;
		param.sched_priority = priority;
		
		
		if(ret = pthread_setschedparam(threadID, policy, &param) != 0){
			std::cout << "Can not set thread parameters " << ret << std::endl;
			return false;
		}
		return true;
	}
	

	
private:
	
	std::time_t m_start_time = 0;
	PyObj_ptr m_callback;
	PyObj_ptr m_on_thread_event;
	volatile bool m_run;
	cv::VideoCapture m_camera_io;
	std::mutex m_resource_lock; // syncronized main thread and cam thread for create and kill motion detector ptr
	boost::scoped_ptr<::MotionDetection> m_motion_detect; 
	boost::scoped_ptr<::VideoWriterThread> m_video_io;
	boost::scoped_ptr<boost::thread> m_stream_thread;
	
	
	template<typename A>
	void process(A source){
		try{
			VideoFinalize vf_ = VideoFinalize(&m_camera_io);
			::pyCallback(m_on_thread_event.object, events::thread_start);
			m_camera_io.open(source);
			m_camera_io.set(CV_CAP_PROP_FPS,9);
			
			if (!m_camera_io.isOpened()){
				::pyCallback(m_on_thread_event.object, events::device_open_error);
				return;
			}
			
			::pyCallback(m_on_thread_event.object, events::device_open_success);
			
			std::stringstream _cam_name;
			_cam_name << "CAM" << source;

			cv::Mat frame;

			
			std::vector<int> opt;
			opt.push_back(CV_IMWRITE_JPEG_QUALITY);
			opt.push_back(70);
			
			std::vector<uchar> buff;
			
			while(m_run){
				if(!m_camera_io.read(frame)){
					::pyCallback(m_on_thread_event.object, events::device_disconnect);
					m_camera_io.release();
					return;
				}
				m_resource_lock.lock();
				if (m_motion_detect!=nullptr){
					m_motion_detect->detect(frame);
				}
				m_resource_lock.unlock();
				int bs =0;
				cv::Size size = frame.size();
				cv::Size text_size = cv::getTextSize(_cam_name.str(),cv::FONT_HERSHEY_PLAIN,1.5,1,&bs);
				cv::Point2i p = cv::Point2i((size.width - text_size.width) ,size.height );
				cv::putText(frame, _cam_name.str(),p ,cv::FONT_HERSHEY_PLAIN, 1.5,  cv::Scalar(0,0,255,255));
				
				m_resource_lock.lock();
				if(m_video_io != nullptr){
					cv::Mat* frame_ = new cv::Mat();
					frame.copyTo(*frame_);
					m_video_io->add(frame_);
					cv::circle(frame, cv::Point2i(10,10), 7, cv::Scalar(0,0,255,255),CV_FILLED);
				}
				m_resource_lock.unlock();
				
				if(cv::imencode(".jpg",frame,buff,opt)){
					std::string img_bytes(buff.begin(),buff.end());
					::pyCallback(m_callback.object , img_bytes);
				}
			}
			if(m_video_io != nullptr){
				m_video_io->stop();
			}
		}catch(std::exception& e){
			std::cout << "what EXCEPTION " << e.what() << std::endl;
			::pyCallback(m_on_thread_event.object, events::unhandled_error, e.what());
			return;
		}
		std::cout << "stop capture thread" << (this)  << std::endl;
		::pyCallback(m_on_thread_event.object, events::thread_stop);
	}
};

// функция для сборки видеоряда из кадров
bool make_video(std::string name, boost::python::list images, char* codec){
	GilLock gil = ::GilLock();
	
	std::vector<std::string> arr;
	
	for (int i = 0; i < len(images); ++i)
    {
		std::string str = boost::python::extract<std::string>(images[i]);
		arr.push_back(str);
    }
    
    
    Py_BEGIN_ALLOW_THREADS;
    cv::VideoWriter video_io(name, CV_FOURCC(codec[0], codec[1], codec[2], codec[3]), 5,cv::Size(640, 480),true);
	
	for (auto const& frame : arr){
		video_io.write(cv::imdecode(std::vector<uchar>(frame.begin(), frame.end()),CV_LOAD_IMAGE_COLOR));
	}
	video_io.release();
	Py_END_ALLOW_THREADS;
}


BOOST_PYTHON_MEMBER_FUNCTION_OVERLOADS(ovl_detect_crop, CamStream::enableMotinDetect,2,3)
BOOST_PYTHON_MEMBER_FUNCTION_OVERLOADS(ovl_detect, CamStream::enableMotinDetect,1,2)
BOOST_PYTHON_MEMBER_FUNCTION_OVERLOADS(ovl_recorder, CamStream::startRecord,2,3)

BOOST_PYTHON_MODULE(camstream)
{
	PyEval_InitThreads();
	
	cv::Size defaut_vid_size(640,480);
	
	def("make_video",&make_video);
	
	class_<::CamStream, boost::shared_ptr<CamStream>,boost::noncopyable>("CamStream", init<>())
	

		.def("enableDetect", &CamStream::enableMotinDetect,ovl_detect_crop(("callback",arg("area")=0,arg("sens")=.1)))

		.def("disableDetect", &CamStream::stopMotionDetect)
		.def("isEnabledDetect", &CamStream::detectorIsEnabled)
		.def("getState", &CamStream::getState)
		.def("onCaptureUpdate", &CamStream::onCaptureUpdate)
		.def("onThreadEvent", &CamStream::onThreadEvent)
		.def("start", &CamStream::start<int>)
		.def("start", &CamStream::start<std::string>)
		.def("stop", &CamStream::stop)
		.def("stopAssync", &CamStream::stopAssync)
		.def("schedule", &CamStream::schedule)
		.def("startRecord", &CamStream::startRecord,ovl_recorder())
		.def("stopRecord", &CamStream::stopRecord)
		.add_property("isRunning", &CamStream::isRunning);
		
		
	enum_<CamStream::events>("events")
		.value("thread_start", CamStream::thread_start)
		.value("thread_stop", CamStream::thread_stop)
		.value("device_open_error",CamStream::device_open_error)
		.value("device_open_success",CamStream::device_open_success)
		.value("device_disconnect", CamStream::device_disconnect)
		.value("unhandled_error",CamStream::unhandled_error);
		
	class_<cv::Rect>("Rect")
		.def(init<>())
		.def(init<uint32_t,uint32_t,uint32_t,uint32_t>())
		.def("__str__", &rect_to_st)
		.def("toDict", &rect_to_dict)
		.def_readwrite("x", &cv::Rect::x)
		.def_readwrite("y", &cv::Rect::y)
		.def_readwrite("width", &cv::Rect::width)
		.def_readwrite("height", &cv::Rect::height);

	class_<cv::Size>("Size")
		.def(init<int,int>())
		.def("area", &cv::Size::area)
		.def_readwrite("height", &cv::Size::height)
		.def_readwrite("width", &cv::Size::width);
		
	
}
