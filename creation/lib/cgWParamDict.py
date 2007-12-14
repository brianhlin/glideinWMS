#######################################################
#
# Glidein creation module
# Classes and functions needed to handle dictionary files
# created out of the parameter object
#
#######################################################

import os,os.path,shutil,string
import cgWParams
import cgWDictFile
import cgWCreate
import cgWConsts

# internal, can only be used for multiple inheritance
class glideinCommonDicts:
    def create_dirs(self):
        cgWDictFile.glideinCommonDicts.create_dirs(self)
        try:
            os.mkdir(self.monitor_dir)
        except OSError,e:
            cgWDictFile.glideinCommonDicts.delete_dirs(self)
            raise RuntimeError,"Failed to create dir: %s"%e

        try:
            os.symlink(self.monitor_dir,os.path.join(self.submit_dir,"monitor"))
        except OSError, e:
            cgWDictFile.glideinCommonDicts.delete_dirs(self)
            shutil.rmtree(self.monitor_dir)
            raise RuntimeError,"Failed to create symlink %s: %s"%(os.path.join(self.submit_dir,"monitor"),e)

    def delete_dirs(self):
        cgWDictFile.glideinCommonDicts.delete_dirs(self)
        shutil.rmtree(self.monitor_dir)

class glideinMainDicts(glideinCommonDicts,cgWDictFile.glideinMainDicts):
    def __init__(self,params):
        cgWDictFile.glideinMainDicts.__init__(self,params.submit_dir,params.stage_dir)
        self.monitor_dir=params.monitor_dir
        self.params=params

    def populate(self,params=None):
        if params==None:
            params=self.params
        
        # Load initial system scripts
        # These should be executed before the other scripts
        for script_name in ('setup_x509.sh',"validate_node.sh"):
            self.dicts['script_list'].add_from_file(script_name,None,os.path.join(params.src_dir,script_name))

        # put user files in stage
        for file in params.files:
            add_file_unparsed(file,self.dicts)

        #load condor tarball
        if params.condor.tar_file!=None: # condor tarball available
            self.dicts['subsystem_list'].add_from_file(cgWConsts.CONDOR_FILE,("TRUE",cgWConsts.CONDOR_DIR,cgWConsts.CONDOR_ATTR),params.condor.tar_file)
        else: # create a new tarball
            condor_fd=cgWCreate.create_condor_tar_fd(params.condor.base_dir)
            self.dicts['subsystem_list'].add_from_fd(cgWConsts.CONDOR_FILE,("TRUE",cgWConsts.CONDOR_DIR,cgWConsts.CONDOR_ATTR),condor_fd)
            condor_fd.close()

        #load system files
        for file_name in ('parse_starterlog.awk',"condor_config"):
            self.dicts['file_list'].add_from_file(file_name,None,os.path.join(params.src_dir,file_name))
        self.dicts['vars'].load(params.src_dir,'condor_vars.lst',change_self=False,set_not_changed=False)

        # put user attributes into config files
        for attr_name in params.attrs.keys():
            add_attr_unparsed(attr_name, params.attrs[attr_name],self.dicts,"main")

        # add the basic standard params
        self.dicts['params'].add("GLIDEIN_Collector",'Fake')
        
        # this must be the last script in the list
        for script_name in (cgWConsts.CONDOR_STARTUP_FILE,):
            self.dicts['script_list'].add_from_file(script_name,None,os.path.join(params.src_dir,script_name))
        self.dicts['description'].add(cgWConsts.CONDOR_STARTUP_FILE,"last_script")

        # populate the glidein file
        glidein_dict=self.dicts['glidein']
        glidein_dict.add('FactoryName',params.factory_name)
        glidein_dict.add('GlideinName',params.glidein_name)
        glidein_dict.add('WebURL',params.web_url)

class glideinEntryDicts(glideinCommonDicts,cgWDictFile.glideinEntryDicts):
    def __init__(self,
                 glidein_main_dicts, # must be an instance of glideinMainDicts
                 entry_name):
        cgWDictFile.glideinEntryDicts.__init__(self,glidein_main_dicts,entry_name)
        self.monitor_dir=cgWConsts.get_entry_monitor_dir(glidein_main_dicts.monitor_dir,entry_name)
        self.params=glidein_main_dicts.params

    def erase(self):
        cgWDictFile.glideinEntryDicts.erase(self)
        self.dicts['condor_jdl']=cgWCreate.GlideinSubmitDictFile(self.submit_dir,cgWConsts.SUBMIT_FILE)
        
    def load(self): #will use glidein_main_dicts data, so it must be loaded first
        cgWDictFile.glideinEntryDicts.load(self)
        self.dicts['condor_jdl'].load()

    def save_final(self,set_readonly=True):
        summary_signature=self.glidein_main_dicts['summary_signature']
        entry_stage_dir=cgWConsts.get_entry_stage_dir("",self.entry_name)
        
        self.dicts['condor_jdl'].finalize(summary_signature['main'][0],summary_signature[entry_stage_dir][0],
                                          summary_signature['main'][1],summary_signature[entry_stage_dir][1])
        self.dicts['condor_jdl'].save(set_readonly=set_readonly)
        
    
    def populate(self,schedd_name,params=None):
        if params==None:
            params=self.params

        entry_params=params.entries[self.entry_name]

        # put user files in stage
        for file in entry_params.files:
            add_file_unparsed(file,self.dicts)

        #load system files
        self.dicts['vars'].load(params.src_dir,'condor_vars.lst.entry',change_self=False,set_not_changed=False)
        for file_name in ("nodes.blacklist",):
            self.dicts['file_list'].add_from_file(file_name,"nocache",os.path.join(params.src_dir,file_name))
        
        # put user attributes into config files
        for attr_name in entry_params.attrs.keys():
            add_attr_unparsed(attr_name, entry_params.attrs[attr_name],self.dicts,self.entry_name)

        # populate complex files
        populate_job_descript(self.dicts['job_descript'],
                              self.entry_name,entry_params)

        self.dicts['condor_jdl'].populate(cgWConsts.STARTUP_FILE,
                                          params.factory_name,params.glidein_name,self.entry_name,
                                          entry_params.gridtype,entry_params.gatekeeper,entry_params.rsl,
                                          params.web_url,entry_params.proxy_url,entry_params.work_dir)

        
################################################
#
# This Class contains coth the main and
# the entry dicts
#
################################################

class glideinDicts(cgWDictFile.glideinDicts):
    def __init__(self,params,
                 entry_list=None): # if None, get it from params
        if entry_list==None:
            entry_list=params.entries.keys()

        self.params=params
        self.submit_dir=params.submit_dir
        self.stage_dir=params.stage_dir

        self.main_dicts=glideinMainDicts(params)
        self.entry_list=entry_list[:]
        self.entry_dicts={}
        for entry_name in entry_list:
            self.entry_dicts[entry_name]=glideinEntryDicts(self.main_dicts,entry_name)
        return

    def populate(self,params=None): # will update params (or self.params)
        if params==None:
            params=self.params
        
        self.main_dicts.populate(params)
        self.main_dicts.dicts['glidein'].add('Entries',string.join(self.entry_list,','))

        # make sure all the schedds are defined
        # if not, define them, in place, so thet it get recorded
        global_schedd_names=string.split(params.schedd_name,',')
        global_schedd_idx=0
        for entry_name in self.entry_list:
            if params.entries[entry_name].schedd_name==None:
                # use one of the global ones if specific not provided
                schedd_name=global_schedd_names[global_schedd_idx%len(global_schedd_names)]
                global_schedd_idx=global_schedd_idx+1
                params.subparams.data['entries'][entry_name]['schedd_name']=schedd_name

        for entry_name in self.entry_list:
            self.entry_dicts[entry_name].populate(params)

############################################################
#
# P R I V A T E - Do not use
# 
############################################################

#############################################
# Add a user file residing in the stage area
# file as described by Params.file_defaults
def add_file_unparsed(file,dicts):
    absfname=file.absfname
    if absfname==None:
        raise RuntimeError, "Found a file element without an absname: %s"%file
    
    relfname=file.relfname
    if relfname==None:
        relfname=os.path.basename(absfname) # defualt is the final part of absfname
    if len(relfname)<1:
        raise RuntimeError, "Found a file element with an empty relfname: %s"%file

    is_const=eval(file.const,{},{})
    is_executable=eval(file.executable,{},{})
    do_untar=eval(file.untar,{},{})

    if is_executable: # a script
        if not is_const:
            raise RuntimeError, "A file cannot be executable if it is not constant: %s"%file
    
        if do_untar:
            raise RuntimeError, "A tar file cannot be executable: %s"%file

        dicts['script_list'].add_from_file(relfname,None,absfname)
    elif do_untar: # a tarball
        if not is_const:
            raise RuntimeError, "A file cannot be untarred if it is not constant: %s"%file

        wnsubdir=file.untar_options.dir
        if wnsubdir==None:
            wnsubdir=string.split(relfname,'.',1)[0] # deafult is relfname up to the first .

        #temporary, should be fixed in future versions
        if file.untar_options.absdir_outattr==None:
            raise RuntimeError, 'Currently untar_options.absdir_outattr must be defined: %s'%file
        
        cond_attr=file.untar_options.cond_attr
        dicts['subsystem_list'].add_from_file(relfname,(cond_attr,wnsubdir,file.untar_options.absdir_outattr),absfname)
        if cond_attr!="TRUE":
            dicts['params'].add(cond_attr,0)
    else: # not executable nor tarball => simple file
        if is_const:
            val=None
        else:
            val='nocache'
        dicts['file_list'].add_from_file(relfname,val,absfname)

#######################
# Register an attribute
# attr_obj as described by Params.attr_defaults
def add_attr_unparsed(attr_name,attr_obj,dicts,description):
    try:
        add_attr_unparsed_real(attr_name,attr_obj,dicts)
    except RuntimeError,e:
        raise RuntimeError, "Error parsing attr %s[%s]: %s"%(description,attr_name,str(e))

def add_attr_unparsed_real(attr_name,attr_obj,dicts):
    if attr_obj.value==None:
        raise RuntimeError, "Attribute '%s' does not have a value: %s"%(attr_name,attr_obj)
    
    do_publish=eval(attr_obj.publish,{},{})
    is_parameter=eval(attr_obj.parameter,{},{})
    is_const=eval(attr_obj.const,{},{})
    attr_val=cgWParams.extract_attr_val(attr_obj)
    
    if do_publish: # publish in factory ClassAd
        if is_parameter: # but also push to glidein
            if is_const:
                dicts['attrs'].add(attr_name,attr_val)
                dicts['consts'].add(attr_name,attr_val)
            else:
                dicts['params'].add(attr_name,attr_val)
        else: # only publish
            if (not is_const):
                raise RuntimeError, "Published attribute '%s' must be either a parameter or constant: %s"%(attr_name,attr_obj)
            
            dicts['attrs'].add(attr_name,attr_val)
    else: # do not publish, only to glidein
        if is_parameter:
            if is_const:
                dicts['consts'].add(attr_name,attr_val)
            else:
                raise RuntimeError, "Parameter attributes '%s' must be either a published or constant: %s"%(attr_name,attr_obj)
        else:
            raise RuntimeError, "Attributes '%s' must be either a published or parameters: %s"%(attr_name,attr_obj) 

    if is_parameter:
        do_glidein_publish=eval(attr_obj.glidein_publish,{},{})
        do_job_publish=eval(attr_obj.job_publish,{},{})

        if do_glidein_publish or do_job_publish:
            # need to add a line only if will be published
            if dicts['vars'].has_key(attr_name):
                # already in the var file, check if compatible
                attr_var_el=dicts['vars'][attr_name]
                attr_var_type=attr_var_el[0]
                if (((attr_obj.type=="int") and (attr_var_type!='I')) or
                    ((attr_obj.type=="string") and (attr_var_type=='I'))):
                    raise RuntimeError, "Types not compatible (%s,%s)"%(attr_obj.type,attr_var_type)
                attr_var_export=attr_var_el[4]
                if do_glidein_publish and (attr_var_export=='N'):
                    raise RuntimeError, "Cannot force glidein publishing"
                attr_var_job_publish=attr_var_el[5]
                if do_job_publish and (attr_var_job_publish=='-'):
                    raise RuntimeError, "Cannot force job publishing"
            else:
                dicts['vars'].add_extended(attr_name,attr_obj.type=="string",None,None,False,do_glidein_publish,do_job_publish)

def populate_job_descript(job_descript_dict,        # will be modified
                          entry_name,entry_params):
    job_descript_dict.add('EntryName',entry_name)
    job_descript_dict.add('GridType',entry_params.gridtype)
    job_descript_dict.add('Gatekeeper',entry_params.gatekeeper)
    if entry_params.rsl!=None:
        job_descript_dict.add('GlobusRSL',entry_params.rsl)
    job_descript_dict.add('Schedd',entry_params.schedd_name)
    job_descript_dict.add('StartupDir',entry_params.work_dir)
    if entry_params.proxy_url!=None:
        job_descript_dict.add('ProxyURL',entry_params.proxy_url)

    
#######################
# Simply symlink a file
def symlink_file(infile,outfile):
    try:
        os.symlink(infile,outfile)
    except IOError, e:
        raise RuntimeError, "Error symlink %s in %s: %s"%(infile,outfile,e)

###########################################################
#
# CVS info
#
# $Id: cgWParamDict.py,v 1.19 2007/12/14 16:56:55 sfiligoi Exp $
#
# Log:
#  $Log: cgWParamDict.py,v $
#  Revision 1.19  2007/12/14 16:56:55  sfiligoi
#  Fix typo
#
#  Revision 1.18  2007/12/14 16:53:58  sfiligoi
#  Fix typo
#
#  Revision 1.17  2007/12/14 16:30:07  sfiligoi
#  Fix typo
#
#  Revision 1.16  2007/12/14 16:28:53  sfiligoi
#  Move directory creation into the Dict classes
#
#  Revision 1.15  2007/12/14 14:36:11  sfiligoi
#  Make saving optional if the dictionary has not been changed
#
#  Revision 1.14  2007/12/14 00:04:36  sfiligoi
#  Fix typo
#
#  Revision 1.13  2007/12/13 23:54:51  sfiligoi
#  Fix entry attr processing
#
#  Revision 1.11  2007/12/13 22:35:10  sfiligoi
#  Move entry specific arguments into the creation stage
#
#  Revision 1.8  2007/12/13 20:19:46  sfiligoi
#  Move condor jdl into entry subdir, and implement it via a dictionary
#
#  Revision 1.4  2007/12/12 00:35:36  sfiligoi
#  Move creation of glidein and job_descript files from cgWCreate to cgWParamDict
#
#  Revision 1.3  2007/12/11 23:52:40  sfiligoi
#  Create monitor_dir in a single place
#
#  Revision 1.1  2007/12/11 23:09:54  sfiligoi
#  Move the population of dictionaries into cgWParamDict
#
#
###########################################################
