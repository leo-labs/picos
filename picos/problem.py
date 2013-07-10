# coding: utf-8

#-------------------------------------------------------------------
#Picos 0.1.4 : A pyton Interface To Conic Optimization Solvers
#Copyright (C) 2012  Guillaume Sagnol
#
#This program is free software: you can redistribute it and/or modify
#it under the terms of the GNU General Public License as published by
#the Free Software Foundation, either version 3 of the License, or
#(at your option) any later version.
#
#This program is distributed in the hope that it will be useful,
#but WITHOUT ANY WARRANTY; without even the implied warranty of
#MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#GNU General Public License for more details.
#
#You should have received a copy of the GNU General Public License
#along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
#For any information, please contact:
#Guillaume Sagnol
#sagnol@zib.de
#Konrad Zuse Zentrum für Informationstechnik Berlin (ZIB)
#Takustrasse 7
#D-14195 Berlin-Dahlem
#Germany 
#-------------------------------------------------------------------

import cvxopt as cvx
import numpy as np
import sys

from .tools import *
from .expression import *
from .constraint import *

__all__=[ 'Problem','Variable']

global INFINITY
INFINITY=1e16

class Problem(object):
        """This class represents an optimization problem.
        The constructor creates an empty problem.
        Some options can be provided under the form
        ``key = value``.
        See the list of available options
        in the doc of :func:`set_all_options_to_default() <picos.Problem.set_all_options_to_default>`
        """
        
        def __init__(self,**options):
                self.objective = ('find',None) #feasibility problem only
                self.constraints = []
                """list of all constraints"""
                self.variables = {}
                """dictionary of variables indexed by variable names"""
                self.countVar=0
                """number of (multidimensional) variables"""
                self.countCons=0
                """numner of (multidimensional) constraints"""
                self.numberOfVars=0
                """total number of (scalar) variables"""
                self.numberAffConstraints=0
                """total number of (scalar) affine constraints"""
                self.numberConeVars=0
                """number of auxilary variables required to handle the SOC constraints"""
                self.numberConeConstraints=0
                """number of SOC constraints"""
                self.numberLSEConstraints=0
                """number of LogSumExp constraints (+1 if the objective is a LogSumExp)"""
                self.numberLSEVars=0
                """number of vars in LogSumExp expressions"""
                self.numberQuadConstraints=0
                """number of quadratic constraints (+1 if the objective is quadratic)"""
                self.numberQuadNNZ=0
                """number of nonzero entries in the matrices defining the quadratic expressions"""
                self.numberSDPConstraints=0
                """number of SDP constraints"""
                self.numberSDPVars=0
                """size of the s-vecotrized matrices involved in SDP constraints"""
                self.countGeomean=0
                """number of geomean (and other nonstandard convex) inequalities"""
                self.cvxoptVars={'c':None,
                                'A':None,'b':None, #equalities
                                'Gl':None,'hl':None, #inequalities
                                'Gq':None,'hq':None, #quadratic cone
                                'Gs':None,'hs':None, #semidefinite cone
                                'F':None,'g':None, #GP constraints
                                'quadcons': None} #other quads
                
                self.gurobi_Instance = None
                self.grbvar = {}
                self.grb_boundcons = None
                
                self.cplex_Instance = None
                self.cplex_boundcons = None
                
                self.msk_env=None
                self.msk_task=None
                self.msk_fxd=None
                self.msk_scaledcols=None
                self.msk_fxdconevars = None

                self.scip_solver = None
                self.scip_vars = None
                self.scip_obj = None
                
                self.groupsOfConstraints = {}
                self.listOfVars = {}
                self.consNumbering=[]
                #next constraint to consider in a makeXXX_instance
                self.last_updated_constraint=0 #next constraint to consider in a makeXXX_instance
                
                self._options = _NonWritableDict()
                if options is None: options={}
                self.set_all_options_to_default()
                self.update_options(**options)

                self.number_solutions=0
                                
                self.longestkey=0 #for a nice display of constraints
                self.varNames=[]
                
                self.status='unsolved'
                """status returned by the solver. The default when
                   a new problem is created is 'unsolved'.
                """
                
                self.obj_passed = []
                """list of solver instances where the objective has been passed"""

        def __str__(self):
                probstr='---------------------\n'               
                probstr+='optimization problem  ({0}):\n'.format(self.type)
                probstr+='{0} variables, {1} affine constraints'.format(
                                self.numberOfVars,self.numberAffConstraints)
                                
                if self.numberConeVars>0:
                        probstr+=', {0} vars in {1} SO cones'.format(
                                self.numberConeVars,self.numberConeConstraints)
                if self.numberLSEConstraints>0:
                        probstr+=', {0} vars in {1} LOG-SUM-EXP'.format(
                                self.numberLSEVars,self.numberLSEConstraints)
                if self.numberSDPConstraints>0:
                        probstr+=', {0} vars in {1} SD cones'.format(
                                self.numberSDPVars,self.numberSDPConstraints)
                if self.numberQuadConstraints>0:
                        probstr+=', {0} nnz  in {1} quad constraints'.format(
                                self.numberQuadNNZ,self.numberQuadConstraints)
                probstr+='\n'

                printedlis=[]
                for vkey in self.variables.keys():
                        if vkey.startswith('_geo') or vkey.startswith('_nop'):
                                continue
                        if '[' in vkey and ']' in vkey:
                                lisname=vkey[:vkey.index('[')]
                                if not lisname in printedlis:
                                        printedlis.append(lisname)
                                        var=self.listOfVars[lisname]
                                        probstr+='\n'+lisname+' \t: '
                                        probstr+=var['type']+' of '+str(var['numvars'])+' variables, '
                                        if var['size']=='different':
                                                probstr+='different sizes'
                                        else:
                                                probstr+=str(var['size'])
                                        if var['vtype']=='different':
                                                probstr+=', different type'
                                        else:
                                                probstr+=', '+var['vtype']
                                        probstr += var['bnd']
                        else:                   
                                var = self.variables[vkey]
                                probstr+='\n'+vkey+' \t: '+str(var.size)+', '+var.vtype+var._bndtext
                probstr+='\n'
                if self.objective[0]=='max':
                        probstr+='\n\tmaximize '+self.objective[1].string+'\n'
                elif self.objective[0]=='min':
                        probstr+='\n\tminimize '+self.objective[1].string+'\n'
                elif self.objective[0]=='find':
                        probstr+='\n\tfind vars\n'
                probstr+='such that\n'
                if self.countCons==0:
                        probstr+='  []\n'
                k=0
                while k<self.countCons:
                        if k in self.groupsOfConstraints.keys():
                                lcur=len(self.groupsOfConstraints[k][2])                                
                                if lcur>0:
                                        lcur+=2
                                        probstr+='('+self.groupsOfConstraints[k][2]+')'
                                if self.longestkey==0:
                                        ntabs=0
                                else:
                                        ntabs=int(np.ceil((self.longestkey+2)/8.0))
                                missingtabs=int(  np.ceil(((ntabs*8)-lcur)/8.0)  )
                                for i in range(missingtabs):
                                        probstr+='\t'
                                if lcur>0:
                                        probstr+=': '
                                else:
                                        probstr+='  '
                                probstr+=self.groupsOfConstraints[k][1]
                                k=self.groupsOfConstraints[k][0]+1
                        else:
                                probstr+=self.constraints[k].keyconstring(self.longestkey)+'\n'
                                k+=1
                probstr+='---------------------'
                return probstr
        

        """
        ----------------------------------------------------------------
        --                       Utilities                            --
        ----------------------------------------------------------------
        """

        def reset_solver_instances(self):
                self.cvxoptVars={'c':None,
                                'A':None,'b':None, #equalities
                                'Gl':None,'hl':None, #inequalities
                                'Gq':None,'hq':None, #quadratic cone
                                'Gs':None,'hs':None, #semidefinite cone
                                'F':None,'g':None, #GP constraints
                                'quadcons': None} #other quads
                
                self.gurobi_Instance = None
                self.grbvar = {}
                self.grb_boundcons = None
                
                self.cplex_Instance = None
                self.cplex_boundcons = None
                
                self.msk_env=None
                self.msk_task=None
                self.msk_scaledcols=None
                self.msk_fxd=None
                self.msk_fxdconevars = None

                self.scip_solver = None
                self.scip_vars = None
                self.scip_obj = None
                for cons in self.constraints:
                        cons.passed = []
                self.obj_passed = []
                for var in self.variables.values():
                        var.passed=[]
        
        def remove_all_constraints(self):
                """
                Removes all constraints from the problem
                This function does not remove *hard-coded bounds* on variables;
                use the function :func:`remove_all_variable_bounds() <picos.Problem.remove_all_variable_bounds>`
                to do so.
                """
                self.numberConeConstraints = 0
                self.numberAffConstraints = 0
                self.numberQuadConstraints = 0
                self.numberSDPConstraints = 0
                self.numberLSEConstraints = 0
                self.countGeomean = 0
                self.consNumbering=[]
                self.groupsOfConstraints ={}
                self.numberConeVars=0
                self.numberSDPVars=0
                self.countCons=0
                self.constraints = []
                self.numberQuadNNZ=0
                self.numberLSEVars = 0
                self.last_updated_constraint = 0
                self.countGeomean=0
                if self.objective[0] is not 'find':
                        if self.objective[1] is not None:
                                expr=self.objective[1]
                                if isinstance(expr,QuadExp):
                                        self.numberQuadNNZ=expr.nnz()
                                if isinstance(expr,LogSumExp):
                                        self.numberLSEVars=expr.Exp.size[0]*expr.Exp.size[1]
                self.reset_solver_instances()
                        
        def remove_all_variable_bounds(self):
                """
                remove all the lower and upper bounds on variables (i.e,, 
                *hard-coded bounds* passed in the attribute ``bnd`` of the variables.
                """
                for var in self.variables.values():
                        var.bnd._reset()
                
        
        def obj_value(self):
                """
                If the problem was already solved, returns the objective value.
                Otherwise, it raises an ``AttributeError``.
                """
                return self.objective[1].eval()[0]

        def get_varName(self,Id):
                return [k for k in self.variables.keys() if  self.variables[k].Id==Id][0]
        
        def set_objective(self,typ,expr):
                """
                Defines the objective function of the problem.
                
                :param typ: can be either ``'max'`` (maximization problem),
                            ``'min'`` (minimization problem),
                            or ``'find'`` (feasibility problem).
                :type typ: str.
                :param expr: an :class:`Expression <picos.Expression>`. The expression to be minimized
                             or maximized. This parameter will be ignored
                             if ``typ=='find'``.
                """
                if typ=='find':
                        self.objective=(typ,expr)
                        return
                if (isinstance(expr,AffinExp) and expr.size<>(1,1)):
                        raise Exception('objective should be scalar')
                if not (isinstance(expr,AffinExp) or isinstance(expr,LogSumExp)
                        or isinstance(expr,QuadExp) or isinstance(expr,GeneralFun)):
                        raise Exception('unsupported objective')
                if isinstance(self.objective[1],LogSumExp):
                        oldexp = self.objective[1]
                        self.numberLSEConstraints-=1
                        self.numberLSEVars-=oldexp.Exp.size[0]*oldexp.Exp.size[1]
                if isinstance(self.objective[1],QuadExp):
                        oldexp = self.objective[1]
                        self.numberQuadConstraints-=1
                        self.numberQuadNNZ-=oldexp.nnz()
                if isinstance(expr,LogSumExp):
                        self.numberLSEVars+=expr.Exp.size[0]*expr.Exp.size[1]
                        self.numberLSEConstraints+=1
                if isinstance(expr,QuadExp):
                        self.numberQuadConstraints+=1
                        self.numberQuadNNZ+=expr.nnz()
                self.objective=(typ,expr)
                self.obj_passed = []#reset the solvers which know this objective function
        
        def set_var_value(self,name,value,optimalvar=False):
                """
                Sets the :attr:`value<picos.Variable.value>` attribute of the
                given variable.
                
                ..
                   This can be useful to check
                   the value of a complicated :class:`Expression <picos.Expression>`,
                   or to use a solver with a *hot start* option.
                
                :param name: name of the variable to which the value will be given
                :type name: str.
                :param value: The value to be given. The type of
                              ``value`` must be recognized by the function
                              :func:`_retrieve_matrix() <picos.tools._retrieve_matrix>`,
                              so that it can be parsed into a :func:`cvxopt sparse matrix <cvxopt:cvxopt.spmatrix>`
                              of the desired size.
                
                **Example**
                
                >>> prob=pic.Problem()
                >>> x=prob.add_variable('x',2)
                >>> prob.set_var_value('x',[3,4])  #this is in fact equivalent to x.value=[3,4]
                >>> abs(x)**2
                #quadratic expression: ||x||**2 #
                >>> print (abs(x)**2)
                25.0
                """
                ind = None
                if isinstance(name,tuple): # alternative solution
                        ind=name[0]
                        name=name[1]

                if not name in self.variables.keys():
                        raise Exception('unknown variable name')
                valuemat,valueString=_retrieve_matrix(value,self.variables[name].size)
                if valuemat.size<>self.variables[name].size:
                        raise Exception('should be of size {0}'.format(self.variables[name].size))
                if ind is None:
                        #svectorization for symmetric is done by the value property
                        self.variables[name].value=valuemat
                        if optimalvar:
                                self.number_solutions=max(self.number_solutions,1)
                else:
                        if self.variables[name].vtype=='symmetric':
                                valuemat=svec(valuemat)        
                        self.variables[name].value_alt[ind]=valuemat
                        if optimalvar:
                                self.number_solutions=max(self.number_solutions,ind+1)

        def _makeGandh(self,affExpr):
                """if affExpr is an affine expression,
                this method creates a bloc matrix G to be multiplied by the large
                vectorized vector of all variables,
                and returns the vector h corresponding to the constant term.
                """
                n1=affExpr.size[0]*affExpr.size[1]
                #matrix G               
                I=[]
                J=[]
                V=[]
                for var in affExpr.factors:
                        si = var.startIndex
                        facvar=affExpr.factors[var]
                        if type(facvar)!=cvx.base.spmatrix:
                                facvar=cvx.sparse(facvar)
                        I.extend(facvar.I)
                        J.extend([si+j for j in facvar.J])
                        V.extend(facvar.V)
                G=cvx.spmatrix(V,I,J,(n1,self.numberOfVars))
                
                #is it really sparse ?
                #if cvx.nnz(G)/float(G.size[0]*G.size[1])>0.5:
                #       G=cvx.matrix(G,tc='d')
                #vector h
                if affExpr.constant is None:
                        h=cvx.matrix(0,(n1,1),tc='d')
                else:
                        h=affExpr.constant
                if not isinstance(h,cvx.matrix):
                        h=cvx.matrix(h,tc='d')
                if h.typecode<>'d':
                        h=cvx.matrix(h,tc='d')
                return G,h

                
        def set_all_options_to_default(self):
                """set all the options to their default.
                The following options are available, and can be passed
                as pairs of the form ``key=value`` to :func:`solve() <picos.Problem.solve>` :
                
                * General options common to all solvers:
                
                  * ``verbose = 1`` : verbosity level [0(quiet)|1|2(loud)]
                  
                  * ``solver = None`` : currently the available solvers are
                    ``'cvxopt'``, ``'cplex'``, ``'mosek'``, ``'gurobi'``, ``'smcp'``, ``'zibopt'``.
                    The default
                    ``None`` means that you let picos select a suitable solver for you.
                  
                  * ``tol = 1e-8`` : Relative gap termination tolerance
                    for interior-point optimizers (feasibility and complementary slackness).
                  
                  * ``maxit = None`` : maximum number of iterations
                    (for simplex or interior-point optimizers).
                    *This option is currently ignored by zibopt*.
                  
                  * ``lp_root_method = None`` : algorithm used to solve continuous LP
                    problems, including the root relaxation of mixed integer problems.
                    The default ``None`` selects automatically an algorithm.
                    If set to ``psimplex`` (resp. ``dsimplex``, ``interior``), the solver
                    will use a primal simplex (resp. dual simplex, interior-point) algorithm.
                    *This option currently works only with cplex, mosek and gurobi*.
                    
                  * ``lp_node_method = None`` : algorithm used to solve subproblems
                    at nodes of the branching trees of mixed integer programs.
                    The default ``None`` selects automatically an algorithm.
                    If set to ``psimplex`` (resp. ``dsimplex``, ``interior``), the solver
                    will use a primal simplex (resp. dual simplex, interior-point) algorithm.
                    *This option currently works only with cplex, mosek and gurobi*.
                  
                  * ``timelimit = None`` : time limit for the solver, in seconds. The default
                    ``None`` means no time limit.
                    *This option is currently ignored by cvxopt and smcp*.
                
                  * ``treememory = None``  : size of the buffer for the branch and bound tree,
                    in Megabytes. 
                    *This option currently works only with cplex*.
                    
                  * ``gaplim = 1e-4`` : For mixed integer problems,
                    the solver returns a solution as soon as this value for the gap is reached
                    (relative gap between the primal and the dual bound).
                    
                
                  * ``onlyChangeObjective = False`` : set this option to ``True`` if you have already
                    solved the problem, and want to recompute the solution with a different
                    objective funtion or different parameter settings. This way, the constraints
                    of the problem will not be parsed by picos next
                    time :func:`solve() <picos.Problem.solve>` is called
                    (this can lead to a huge gain of time).
                    
                  * ``noprimals = False`` : if ``True``, do not copy the optimal variable values in the
                    :attr:`value<picos.Variable.value>` attribute of the problem variables.
                    
                  * ``noduals = False`` : if ``True``, do not try to retrieve the dual variables.

                  * ``nbsol = None`` : maximum number of feasible solution nodes visited
                    when solving a mixed integer problem.
                    
                  * ``hotstart = False`` : if ``True``, the MIP optimizer tries to start from
                    the solution
                    specified (even partly) in the :attr:`value<picos.Variable.value>` attribute of the
                    problem variables.
                    *This option currently works only with cplex, mosek and gurobi*.
                                    
                  * ``convert_quad_to_socp_if_needed = True`` : Do we convert the convex quadratics to
                    second order cone constraints when the solver does not handle them directly ?
                                    
                * Specific options available for cvxopt/smcp:
                
                  * ``feastol = None`` : feasibility tolerance passed to `cvx.solvers.options <http://abel.ee.ucla.edu/cvxopt/userguide/coneprog.html#algorithm-parameters>`_
                    If ``feastol`` has the default value ``None``,
                    then the value of the option ``tol`` is used.
                  
                  * ``abstol = None`` : absolute tolerance passed to `cvx.solvers.options <http://abel.ee.ucla.edu/cvxopt/userguide/coneprog.html#algorithm-parameters>`_
                    If ``abstol`` has the default value ``None``,
                    then the value of the option ``tol`` is used.
                  
                  * ``reltol = None`` : relative tolerance passed to `cvx.solvers.options <http://abel.ee.ucla.edu/cvxopt/userguide/coneprog.html#algorithm-parameters>`_
                    If ``reltol`` has the default value ``None``,
                    then the value of the option ``tol``, multiplied by ``10``, is used.
                  
                * Specific options available for cplex:
                
                  * ``cplex_params = {}`` : a dictionary of
                    `cplex parameters <http://pic.dhe.ibm.com/infocenter/cosinfoc/v12r2/index.jsp?topic=%2Filog.odms.cplex.help%2FContent%2FOptimization%2FDocumentation%2FCPLEX%2F_pubskel%2FCPLEX934.html>`_
                    to be set before the cplex
                    optimizer is called. For example,
                    ``cplex_params={'mip.limits.cutpasses' : 5}``
                    will limit the number of cutting plane passes when solving the root node
                    to ``5``.
                    
                  * ``acceptable_gap_at_timelimit = None`` : If the the time limit is reached,
                    the optimization process is aborted only if the current gap is less
                    than this value. The default value ``None`` means that we
                    interrupt the computation regardless of the achieved gap.
                  
                  * ``uboundlimit = None`` : tells CPLEX to stop as soon as an upper
                    bound smaller than this value is found.
                    
                  * ``lboundlimit = None`` : tells CPLEX to stop as soon as a lower
                    bound larger than this value is found.
                  
                  * ``boundMonitor = True`` : tells CPLEX to store information about
                    the evolution of the bounds during the solving process. At the end
                    of the computation, a list of triples ``(time,lowerbound,upperbound)``
                    will be provided in the field ``bounds_monitor`` of the dictionary
                    returned by :func:`solve() <picos.Problem.solve>`.
                  
                * Specific options available for mosek:
                
                  * ``mosek_params = {}`` : a dictionary of
                    `mosek parameters <http://docs.mosek.com/6.0/pyapi/node017.html>`_
                    to be set before the mosek
                    optimizer is called. For example,
                    ``mosek_params={'simplex_abs_tol_piv' : 1e-4}``
                    sets the absolute pivot tolerance of the
                    simplex optimizer to ``1e-4``.
                    
                * Specific options available for gurobi:
                
                  * ``gurobi_params = {}`` : a dictionary of
                    `gurobi parameters <http://www.gurobi.com/documentation/5.0/reference-manual/node653>`_
                    to be set before the gurobi
                    optimizer is called. For example,
                    ``gurobi_params={'NodeLimit' : 25}``
                    limits the number of nodes visited by the MIP optimizer to 25.
                
                """
                #Additional, hidden option (requires a patch of smcp, to use conlp to
                #interface the feasible starting point solver):
                #
                #* 'smcp_feas'=False [if True, use the feasible start solver with SMCP]
                default_options={'tol'            :1e-8,
                                 'feastol'        :None,
                                 'abstol'         :None,
                                 'reltol'         :None,
                                 'maxit'          :None,
                                 'verbose'        :1,
                                 'solver'         :None,
                                 'step_sqp'       :1, #undocumented
                                 'harmonic_steps' :1, #undocumented
                                 'onlyChangeObjective':False,
                                 'noprimals'      :False,
                                 'noduals'        :False,
                                 'smcp_feas'      :False,#undocumented
                                 'nbsol'          :None,
                                 'timelimit'      :None,
                                 'acceptable_gap_at_timelimit'  :None,
                                 'treememory'     :None,
                                 'gaplim'         :1e-4,
                                 'pool_gap'       :None,#undocumented
                                 'pool_size'      :None,#undocumented
                                 'lp_root_method' :None,
                                 'lp_node_method' :None,
                                 'cplex_params'   :{},
                                 'mosek_params'   :{},
                                 'gurobi_params'  :{},
                                 'convert_quad_to_socp_if_needed' : True,
                                 'hotstart'       :False,
                                 'uboundlimit'    :None,
                                 'lboundlimit'    :None,
                                 'boundMonitor'   :False,
                                 'handleBarVars'  :True, #TODOC: for MOSEK, do we handle semidefVars separatly
                                 'handleConeVars' :True, #TODOC: for MOSEK, do we put original variables in cones when possible ?
                                 'solve_via_dual' :False, #TODO set None#TODOC the problem is dualized before being passed to the solver
                                 }
                                 
                                 
                self._options=_NonWritableDict(default_options)
        
        @property
        def options(self):
                return self._options
                
        def set_option(self,key,val):
                """
                Sets the option **key** to the value **val**.
                
                :param key: The key of an option
                            (see the list of keys in the doc of
                            :func:`set_all_options_to_default() <picos.Problem.set_all_options_to_default>`).
                :type key: str.
                :param val: New value for the option.
                """
                if key in ('handleBarVars','handleConeVars')  and val != self.options[key]:
                        self.reset_solver_instances()#because we must pass in make_mosek_instance again.
                if key not in self.options:
                        raise AttributeError('unkown option key :'+str(key))
                self.options._set(key,val)
                if key=='verbose' and isinstance(val,bool):
                        self.options._set('verbose',int(val))
                
                #trick to force the use of mosek6 during the tests:
                #if val=='mosek':
                #        self.options._set('solver','mosek6')
                        
        def update_options(self, **options):
                """
                update the option dictionary, for each pair of the form
                ``key = value``. For a list of available options and their default values,
                see the doc of :func:`set_all_options_to_default() <picos.Problem.set_all_options_to_default>`.
                """
                
                for k in options.keys():
                        self.set_option(k,options[k])
                                        
                
        def _eliminate_useless_variables(self):
                """
                Removes from the problem the variables that do not
                appear in any constraint or in the objective function.
                """
                foundVars = set([])
                for cons in self.constraints:
                        if isinstance(cons.Exp1,AffinExp):
                                foundVars.update(cons.Exp1.factors.keys())
                                foundVars.update(cons.Exp2.factors.keys())
                                if not cons.Exp3 is None:
                                        foundVars.update(cons.Exp3.factors.keys())
                        elif isinstance(cons.Exp1,QuadExp):
                                foundVars.update(cons.Exp1.aff.factors.keys())
                                for ij in cons.Exp1.quad:
                                        foundVars.update(ij)
                        elif isinstance(cons.Exp1,LogSumExp):
                                foundVars.update(cons.Exp1.Exp.factors.keys())
                if not self.objective[1] is None:
                        obj = self.objective[1]
                        if isinstance(obj,AffinExp):
                                foundVars.update(obj.factors.keys())
                        elif isinstance(obj,QuadExp):
                                foundVars.update(obj.aff.factors.keys())
                                for ij in obj.quad:
                                        foundVars.update(ij)
                        elif isinstance(obj,LogSumExp):
                                foundVars.update(obj.Exp.factors.keys())
                
                vars2del =[]
                for vname,v in self.variables.iteritems():
                        if v not in foundVars:
                                vars2del.append(vname)
                
                for vname in sorted(vars2del):
                        self.remove_variable(vname)
                        if self.options['verbose']>1:
                                print('variable '+vname+' was useless and has been removed')

        """
        ----------------------------------------------------------------
        --                TOOLS TO CREATE AN INSTANCE                 --
        ----------------------------------------------------------------
        """

        def add_variable(self,name,size=1, vtype = 'continuous',lower = None,upper =None ):
                """
                adds a variable in the problem,
                and returns the corresponding instance of the :class:`Variable <picos.Variable>`.
                
                For example,
                
                >>> prob=pic.Problem()
                >>> x=prob.add_variable('x',3)
                >>> x
                # variable x:(3 x 1),continuous #
                                
                :param name: The name of the variable.
                :type name: str.
                :param size: The size of the variable.
                             
                             Can be either:
                             
                                * an ``int`` *n* , in which case the variable is a **vector of dimension n**
                                
                                * or a ``tuple`` *(n,m)*, and the variable is a **n x m-matrix**.
                
                :type size: int or tuple.
                :param vtype: variable :attr:`type <picos.Variable.vtype>`. 
                              Can be:
                              
                                * ``'continuous'`` (default),
                                
                                * ``'binary'``: 0/1 variable
                                
                                * ``'integer'``: integer valued variable
                                
                                * ``'symmetric'``: symmetric matrix
                                
                                * ``'semicont'``: 0 or continuous variable satisfying its bounds
                                
                                * ``'semiint'``: 0 or integer variable satisfying its bounds
                
                :type vtype: str.
                :param lower: a lower bound for the variable. Can be either a vector/matrix of the
                              same size as the variable, or a scalar (in which case all elements
                              of the variable have the same lower bound).
                :type lower: Any type recognized by the function
                              :func:`_retrieve_matrix() <picos.tools._retrieve_matrix>`.
                :param upper: an upper bound for the variable. Can be either a vector/matrix of the
                              same size as the variable, or a scalar (in which case all elements
                              of the variable have the same upper bound).
                :type upper: Any type recognized by the function
                              :func:`_retrieve_matrix() <picos.tools._retrieve_matrix>`.
                
                :returns: An instance of the class :class:`Variable <picos.Variable>`.
                #TODOC tutorial examples with bounds and sparse bounds
                """

                if name in self.variables:
                        raise Exception('this variable already exists')
                if isinstance(size,int):
                        size=(size,1)
                if len(size)==1:
                        size=(size[0],1)

                lisname = None
                if '[' in name and ']' in name:#list or dict of variables
                        lisname=name[:name.index('[')]
                        ind=name[name.index('[')+1:name.index(']')]
                        if lisname in self.listOfVars:
                                oldn=self.listOfVars[lisname]['numvars']
                                self.listOfVars[lisname]['numvars']+=1
                                if size<>self.listOfVars[lisname]['size']:
                                        self.listOfVars[lisname]['size']='different'
                                if vtype<>self.listOfVars[lisname]['vtype']:
                                        self.listOfVars[lisname]['vtype']='different'
                                if self.listOfVars[lisname]['type']=='list' and ind<>str(oldn):
                                        self.listOfVars[lisname]['type']='dict'
                        else:
                                self.listOfVars[lisname]={'numvars':1,'size':size,'vtype':vtype}
                                if ind=='0':
                                        self.listOfVars[lisname]['type']='list'
                                else:
                                        self.listOfVars[lisname]['type']='dict'
                
                countvar=self.countVar
                numbervar=self.numberOfVars
                
                if vtype=='symmetric':
                        if size[0]!=size[1]:
                                raise ValueError('symmetric variables must be square')
                        s0=size[0]
                        self.numberOfVars+=s0*(s0+1)/2
                else:
                        self.numberOfVars+=size[0]*size[1]
                self.varNames.append(name)
                self.countVar+=1
                
                #svec operation
                idmat=_svecm1_identity(vtype,size)
                
                self.variables[name]=Variable(name,
                                        size,
                                        countvar,
                                        numbervar,
                                        vtype=vtype,
                                        lower = lower,
                                        upper = upper)
                if lisname is not None:
                        if self.listOfVars[lisname].has_key('bnd'):
                                bndtext = self.listOfVars[lisname]['bnd']
                                thisbnd = self.variables[name]._bndtext
                                if bndtext <> thisbnd:
                                        self.listOfVars[lisname]['bnd'] = ', some bounds'
                        else:
                                self.listOfVars[lisname]['bnd'] = self.variables[name]._bndtext
                
                return self.variables[name]
        
        
        def remove_variable(self,name):
                """
                Removes the variable ``name`` from the problem.
                :param name: name of the variable to remove.
                :type name: str.
                
                .. Warning:: This method does not check if some constraint still involves the variable
                             to be removed.
                """
                if '[' in name and ']' in name:#list or dict of variables
                        lisname=name[:name.index('[')]
                        if lisname in self.listOfVars:
                                varattr = self.listOfVars[lisname]
                                varattr['numvars'] -=1
                                if varattr['numvars']==0:
                                        del self.listOfVars[lisname] #empty list of vars
                if name not in self.variables.keys():
                        raise Exception('variable does not exist. Maybe you tried to remove some item x[i] of the variable x ?')
                self.countVar-=1
                var = self.variables[name]
                sz=var.size
                self.numberOfVars-=sz[0]*sz[1]
                self.varNames.remove(name)
                del self.variables[name]
                self._recomputeStartEndIndices()
                self.reset_solver_instances()
        
        def _recomputeStartEndIndices(self):
                ind=0
                for nam in self.varNames:
                        var = self.variables[nam]
                        var._startIndex=ind
                        if var.vtype=='symmetric':
                                ind+=int((var.size[0]*(var.size[0]+1))/2)
                        else:
                                ind+=var.size[0]*var.size[1]
                        var._endIndex=ind
                        
        def _remove_temporary_variables(self):
                """
                Remove the variables __tmp...
                created by the solvers to cast the problem as socp
                """
                offset = 0
                todel = []
                for nam in self.varNames:
                        var = self.variables[nam]
                        if '__tmp' in nam or '__noconstant' in nam:
                                self.countVar-=1
                                sz=self.variables[nam].size
                                offset += sz[0]*sz[1]
                                self.numberOfVars-=sz[0]*sz[1]
                                #self.varNames.remove(nam)
                                todel.append(nam)
                                del self.variables[nam]
                        else:
                                var._startIndex-=offset
                                var._endIndex-=offset
                
                for nam in todel:
                        self.varNames.remove(nam)
                        
                if '__tmprhs' in self.listOfVars:
                        del self.listOfVars['__tmprhs']
                if '__tmplhs' in self.listOfVars:
                        del self.listOfVars['__tmplhs']
                

        def copy(self):
                """creates a copy of the problem."""
                import copy
                cop=Problem()
                cvars={}
                for (iv,v) in sorted([(v.startIndex,v) for v in self.variables.values()]):
                        cvars[v.name]=cop.add_variable(v.name,v.size,v.vtype)
                for c in self.constraints:
                        """old version doesnt handle conevars and bounded vars
                        c2=copy.deepcopy(c)
                        c2.Exp1=_copy_exp_to_new_vars(c2.Exp1,cvars)
                        c2.Exp2=_copy_exp_to_new_vars(c2.Exp2,cvars)
                        c2.Exp3=_copy_exp_to_new_vars(c2.Exp3,cvars)
                        if c.semidefVar:
                                c2.semidefVar = cvars[c.semidefVar.name]
                        """
                        E1=_copy_exp_to_new_vars(c.Exp1,cvars)
                        E2=_copy_exp_to_new_vars(c.Exp2,cvars)
                        E3=_copy_exp_to_new_vars(c.Exp3,cvars)
                        c2 = Constraint(c.typeOfConstraint,None,E1,E2,E3)
                        cop.add_constraint(c2,c.key)
                obj=_copy_exp_to_new_vars(self.objective[1],cvars)
                cop.set_objective(self.objective[0],obj)
                
                cop.consNumbering=copy.deepcopy(self.consNumbering)
                cop.groupsOfConstraints=copy.deepcopy(self.groupsOfConstraints)
                cop._options=_NonWritableDict(self.options)
                
                return cop
                
        def add_constraint(self,cons, key=None, ret=False):
                """Adds a constraint in the problem.
                
                :param cons: The constraint to be added.
                :type cons: :class:`Constraint <picos.Constraint>`
                :param key: Optional parameter to describe the constraint with a key string.
                :type key: str.
                :param ret: Do you want the added constraint to be returned ?
                            This can be useful to access the dual of this constraint.
                :type ret: bool.
                """
                #SPECIAL CASE OF A NONSTANDARD CONVEX CONSTRAINT
                if isinstance(cons,_Convex_Constraint):
                        for ui,vui in cons.Ptmp.variables.iteritems():
                                uiname = cons.prefix+str(self.countGeomean)+'_'+ui
                                self.add_variable(uiname,vui.size)
                                si = self.variables[uiname].startIndex
                                ei = self.variables[uiname].endIndex
                                self.variables[uiname] = vui
                                self.variables[uiname]._startIndex = si
                                self.variables[uiname]._endIndex = ei
                                self.variables[uiname].name = uiname
                                
                        indcons = self.countCons
                        self.add_list_of_constraints(cons.Ptmp.constraints,key=key)
                        goc = self.groupsOfConstraints[indcons]
                        goc[1]=cons.constring()+'\n'
                        self.countGeomean += 1
                        if ret:
                                return cons
                        else:
                                return
                
                cons.key=key
                if not key is None:
                        self.longestkey=max(self.longestkey,len(key))
                self.constraints.append(cons)
                self.consNumbering.append(self.countCons)
                self.countCons+=1
                if cons.typeOfConstraint[:3]=='lin':
                        self.numberAffConstraints+=(cons.Exp1.size[0]*cons.Exp1.size[1])
                                        
                elif cons.typeOfConstraint[2:]=='cone':
                        self.numberConeVars+=(cons.Exp1.size[0]*cons.Exp1.size[1])+1
                        self.numberConeConstraints+=1
                        if cons.typeOfConstraint[:2]=='RS':
                                self.numberConeVars+=1
                        
                elif cons.typeOfConstraint=='lse':
                        self.numberLSEVars+=(cons.Exp1.size[0]*cons.Exp1.size[1])
                        self.numberLSEConstraints+=1
                elif cons.typeOfConstraint=='quad':
                        self.numberQuadConstraints+=1
                        self.numberQuadNNZ+=cons.Exp1.nnz()
                elif cons.typeOfConstraint[:3]=='sdp':
                        self.numberSDPConstraints+=1
                        self.numberSDPVars+=(cons.Exp1.size[0]*(cons.Exp1.size[0]+1))/2
                        #is it a simple constraint of the form X>>0 ?
                        if cons.semidefVar:
                                cons.semidefVar.semiDef = True
                if ret:
                        return cons
                

        def add_list_of_constraints(self,lst,it=None,indices=None,key=None,ret=False):
                u"""adds a list of constraints in the problem.
                This fonction can be used with python list comprehensions
                (see the example below).
                
                :param lst: list of :class:`Constraint<picos.Constraint>`.
                :param it: Description of the letters which should
                           be used to replace the dummy indices.
                           The function tries to find a template
                           for the string representations of the
                           constraints in the list. If several indices change in the
                           list, their letters should be given as a
                           list of strings, in their order of appearance in the
                           resulting string. For example, if three indices
                           change in the constraints, and you want them to be named
                           ``'i'``, ``'j'`` and ``'k'``, set ``it = ['i','j','k']``.
                           You can also group two indices which always appear together,
                           e.g. if ``'i'`` always appear next to ``'j'`` you
                           could set ``it = [('ij',2),'k']``. Here, the number 2
                           indicates that ``'ij'`` replaces 2 indices.
                           If ``it`` is set to ``None``, or if the function is not
                           able to find a template,
                           the string of the first constraint will be used for
                           the string representation of the list of constraints.
                :type it: None or str or list.
                :param indices: a string to denote the set where the indices belong to.
                :type indices: str.
                :param key: Optional parameter to describe the list of constraints with a key string.
                :type key: str.
                :param ret: Do you want the added list of constraints to be returned ?
                            This can be useful to access the duals of these constraints.
                :type ret: bool.
                                
                **Example:**

                >>> import picos as pic
                >>> import cvxopt as cvx
                >>> prob=pic.Problem()
                >>> x=[prob.add_variable('x[{0}]'.format(i),2) for i in range(5)]
                >>> x #doctest: +NORMALIZE_WHITESPACE
                [# variable x[0]:(2 x 1),continuous #,
                 # variable x[1]:(2 x 1),continuous #,
                 # variable x[2]:(2 x 1),continuous #,
                 # variable x[3]:(2 x 1),continuous #,
                 # variable x[4]:(2 x 1),continuous #]
                >>> y=prob.add_variable('y',5)
                >>> IJ=[(1,2),(2,0),(4,2)]
                >>> w={}
                >>> for ij in IJ:
                ...         w[ij]=prob.add_variable('w[{0}]'.format(ij),3)
                ... 
                >>> u=pic.new_param('u',cvx.matrix([2,5]))
                >>> prob.add_list_of_constraints(
                ... [u.T*x[i]<y[i] for i in range(5)],
                ... 'i',
                ... '[5]')
                >>> 
                >>> prob.add_list_of_constraints(
                ... [abs(w[i,j])<y[j] for (i,j) in IJ],
                ... [('ij',2)],
                ... 'IJ')
                >>> 
                >>> prob.add_list_of_constraints(
                ... [y[t] > y[t+1] for t in range(4)],
                ... 't',
                ... '[4]')
                >>> 
                >>> print prob #doctest: +NORMALIZE_WHITESPACE
                ---------------------
                optimization problem (SOCP):
                24 variables, 9 affine constraints, 12 vars in 3 SO cones
                <BLANKLINE>
                x   : list of 5 variables, (2, 1), continuous
                w   : dict of 3 variables, (3, 1), continuous
                y   : (5, 1), continuous
                <BLANKLINE>
                    find vars
                such that
                  u.T*x[i] < y[i] for all i in [5]
                  ||w[ij]|| < y[ij__1] for all ij in IJ
                  y[t] > y[t+1] for all t in [4]
                ---------------------

                """
                firstCons=self.countCons
                thisconsnums = []
                for ks in lst:
                        self.add_constraint(ks)
                        cstnum = self.consNumbering.pop()
                        thisconsnums.append(cstnum)
                
                self.consNumbering.append(thisconsnums)
                
                
                
                lastCons=self.countCons-1
                if key is None:
                        key=''
                else:
                        self.longestkey=max(self.longestkey,len(key))
                if it is None:
                        strlis='['+str(len(lst))+' constraints (first: '+lst[0].constring()+')]\n'
                else:
                        strlis=' for all '
                        if len(it)>1:
                                strlis+='('                        
                        for x in it:
                                if isinstance(x,tuple):
                                        strlis+=x[0]
                                else:
                                        strlis+=x
                                strlis+=','
                        strlis=strlis[:-1] #remvove the last comma
                        if len(it)>1:
                                strlis+=')'
                        if not indices is None:
                                strlis+=' in '+indices
                        if isinstance(it,tuple) and len(it)==2 and isinstance(it[1],int):
                                it=(it,)
                        if isinstance(it,list):
                                it=tuple(it)
                        if not isinstance(it,tuple):
                                it=(it,)
                        lstr=[l.constring() for l in lst if '(first:' not in l.constring()]
                        try:
                                indstr=putIndices(lstr,it)
                                strlis=indstr+strlis+'\n'
                        except Exception as ex:
                                strlis='['+str(len(lst))+' constraints (first: '+lst[0].constring()+')]\n'
                self.groupsOfConstraints[firstCons]=[lastCons,strlis,key]
                #remove unwanted subgroup of constraints (which are added when we add list of abstract constraints
                goctodel = []
                for goc in self.groupsOfConstraints:
                        if goc > firstCons and goc<=lastCons:
                                goctodel.append(goc)
                for goc in goctodel:
                        del self.groupsOfConstraints[goc]
                if ret:
                        return lst
         

        def get_valued_variable(self,name):
                """
                Returns the value of the variable (as an :func:`cvxopt matrix <cvxopt:cvxopt.matrix>`)
                with the given ``name``.
                If ``name`` refers to a list (resp. dict) of variables,
                named with the template ``name[index]`` (resp. ``name[key]``),
                then the function returns the list (resp. dict)
                of these variables.
                
                :param name: name of the variable, or of a list/dict of variables.
                :type name: str.
                
                .. Warning:: If the problem has not been solved,
                             or if the variable is not valued,
                             this function will raise an Exception.
                """
                exp=self.get_variable(name)
                if isinstance(exp,list):
                        for i in xrange(len(exp)):
                                exp[i]=exp[i].eval()
                elif isinstance(exp,dict):
                        for i in exp:
                                exp[i]=exp[i].eval()
                else:
                        exp=exp.eval()
                return exp
                

        def get_variable(self,name):
                """
                Returns the variable (as a :class:`Variable <picos.Variable>`)
                with the given ``name``.
                If ``name`` refers to a list (resp. dict) of variables,
                named with the template ``name[index]`` (resp. ``name[key]``),
                then the function returns the list (resp. dict)
                of these variables.
                
                :param name: name of the variable, or of a list/dict of variables.
                :type name: str.
                """
                var=name
                if var in self.listOfVars.keys():
                        if self.listOfVars[var]['type']=='dict':
                                rvar={}
                        else:
                                rvar=[0]*self.listOfVars[var]['numvars']
                        seenKeys=[]
                        for ind in [vname[len(var)+1:-1] for vname in self.variables.keys() if \
                                 (vname[:len(var)] ==var and vname[len(var)]=='[')]:
                                if ind.isdigit():
                                        key=int(ind)
                                        if key not in seenKeys:
                                                seenKeys.append(key)
                                        else:
                                                key=ind
                                elif ',' in ind:
                                        isplit=ind.split(',')
                                        if isplit[0].startswith('('):
                                                isplit[0]=isplit[0][1:]
                                        if isplit[-1].endswith(')'):
                                                isplit[-1]=isplit[-1][:-1]
                                        if all([i.isdigit() for i in isplit]):
                                                key=tuple([int(i) for i in isplit])
                                                if key not in seenKeys:
                                                        seenKeys.append(key)
                                                else:
                                                        key=ind
                                        else:
                                                key=ind
                                else:
                                        try:
                                                key=float(ind)
                                        except ValueError:
                                                key=ind
                                rvar[key]=self.variables[var+'['+ind+']']
                        return rvar
                else:
                        return self.variables[var]
                        


        def get_constraint(self,ind):
                u"""
                returns a constraint of the problem.
                
                :param ind: There are two ways to index a constraint.
                            
                               * if ``ind`` is an *int* :math:`n`, then the nth constraint (starting from 0)
                                 will be returned, where all the constraints are counted
                                 in the order where they were passed to the problem.
                               
                               * if ``ind`` is a *tuple* :math:`(k,i)`, then the ith constraint
                                 from the kth group of constraints is returned
                                 (starting from 0). By            
                                 *group of constraints*, it is meant a single constraint
                                 or a list of constraints added together with the
                                 function :func:`add_list_of_constraints() <picos.Problem.add_list_of_constraints>`.
                               
                               * if ``ind`` is a tuple of length 1 :math:`(k,)`,
                                 then the list of constraints of the kth group is returned.
                
                :type ind: int or tuple.
            
                **Example:**
                
                >>> import picos as pic
                >>> import cvxopt as cvx
                >>> prob=pic.Problem()
                >>> x=[prob.add_variable('x[{0}]'.format(i),2) for i in range(5)]
                >>> y=prob.add_variable('y',5)
                >>> prob.add_list_of_constraints(
                ... [(1|x[i])<y[i] for i in range(5)],
                ... 'i',
                ... '[5]')
                >>> prob.add_constraint(y>0)
                >>> print prob #doctest: +NORMALIZE_WHITESPACE
                ---------------------
                optimization problem (LP):
                15 variables, 10 affine constraints
                <BLANKLINE>
                x   : list of 5 variables, (2, 1), continuous
                y   : (5, 1), continuous
                <BLANKLINE>
                    find vars
                such that
                  〈 |1| | x[i] 〉 < y[i] for all i in [5]
                  y > |0|
                ---------------------
                >>> prob.get_constraint(1)                              #2d constraint (numbered from 0)
                # (1x1)-affine constraint: 〈 |1| | x[1] 〉 < y[1] #
                >>> prob.get_constraint((0,3))                          #4th consraint from the 1st group
                # (1x1)-affine constraint: 〈 |1| | x[3] 〉 < y[3] #
                >>> prob.get_constraint((1,))                           #unique constraint of the 2d 'group'
                # (5x1)-affine constraint: y > |0| #
                >>> prob.get_constraint((0,))                           #list of constraints of the 1st group #doctest: +NORMALIZE_WHITESPACE
                [# (1x1)-affine constraint: 〈 |1| | x[0] 〉 < y[0] #,
                 # (1x1)-affine constraint: 〈 |1| | x[1] 〉 < y[1] #,
                 # (1x1)-affine constraint: 〈 |1| | x[2] 〉 < y[2] #,
                 # (1x1)-affine constraint: 〈 |1| | x[3] 〉 < y[3] #,
                 # (1x1)-affine constraint: 〈 |1| | x[4] 〉 < y[4] #]
                >>> prob.get_constraint(5)                              #6th constraint
                # (5x1)-affine constraint: y > |0| #
                
                """
                indtuple=ind
                if isinstance(indtuple,int):
                        return self.constraints[indtuple]
                lsind=self.consNumbering            
                if not( isinstance(indtuple,tuple) or isinstance(indtuple,list)) or (
                                len(indtuple)==0):
                        raise Exception('ind must be an int or a nonempty tuple')
                
                for k in indtuple:
                        if not isinstance(lsind,list):
                                if k==0:
                                        break
                                else:
                                        raise Exception('too many indices')
                        if k>=len(lsind):
                                raise Exception('index is too large')
                        lsind=lsind[k]
                        
                
                if isinstance(lsind,list):
                                #flatten for the case where it is still a list of list
                                return [self.constraints[i] for i in _flatten(lsind)]
                return self.constraints[lsind]
                
        
        def remove_constraint(self,ind):
                """
                Deletes a constraint or a list of constraints of the problem.
                
                :param ind: The indexing of constraints works as in the
                            function :func:`get_constraint() <picos.Problem.get_constraint>`:
                            
                                * if ``ind`` is an integer :math:`n`, the nth constraint
                                  (numbered from 0) is deleted
                                
                                * if ``ind`` is a *tuple* :math:`(k,i)`, then the ith constraint
                                  from the kth group of constraints is deleted
                                  (starting from 0). By            
                                  *group of constraints*, it is meant a single constraint
                                  or a list of constraints added together with the
                                  function :func:`add_list_of_constraints() <picos.Problem.add_list_of_constraints>`.
                                
                                * if ``ind`` is a tuple of length 1 :math:`(k,)`,
                                  then the whole kth group of constraints is deleted.
                
                :type ind: int or tuple.
                
                **Example:**
                
                >>> import picos as pic
                >>> import cvxopt as cvx
                >>> prob=pic.Problem()
                >>> x=[prob.add_variable('x[{0}]'.format(i),2) for i in range(4)]
                >>> y=prob.add_variable('y',4)
                >>> prob.add_list_of_constraints(
                ... [(1|x[i])<y[i] for i in range(4)], 'i', '[5]')
                >>> prob.add_constraint(y>0)
                >>> prob.add_list_of_constraints(
                ... [x[i]<2 for i in range(3)], 'i', '[3]')
                >>> prob.add_constraint(x[3]<1)
                >>> prob.constraints #doctest: +NORMALIZE_WHITESPACE
                [# (1x1)-affine constraint: 〈 |1| | x[0] 〉 < y[0] #,
                 # (1x1)-affine constraint: 〈 |1| | x[1] 〉 < y[1] #,
                 # (1x1)-affine constraint: 〈 |1| | x[2] 〉 < y[2] #,
                 # (1x1)-affine constraint: 〈 |1| | x[3] 〉 < y[3] #,
                 # (4x1)-affine constraint: y > |0| #,
                 # (2x1)-affine constraint: x[0] < |2.0| #,
                 # (2x1)-affine constraint: x[1] < |2.0| #,
                 # (2x1)-affine constraint: x[2] < |2.0| #,
                 # (2x1)-affine constraint: x[3] < |1| #]
                >>> prob.remove_constraint(1)                           #2d constraint (numbered from 0) deleted
                >>> prob.constraints #doctest: +NORMALIZE_WHITESPACE
                [# (1x1)-affine constraint: 〈 |1| | x[0] 〉 < y[0] #, 
                 # (1x1)-affine constraint: 〈 |1| | x[2] 〉 < y[2] #,
                 # (1x1)-affine constraint: 〈 |1| | x[3] 〉 < y[3] #,
                 # (4x1)-affine constraint: y > |0| #,
                 # (2x1)-affine constraint: x[0] < |2.0| #,
                 # (2x1)-affine constraint: x[1] < |2.0| #,
                 # (2x1)-affine constraint: x[2] < |2.0| #,
                 # (2x1)-affine constraint: x[3] < |1| #]
                >>> prob.remove_constraint((1,))                        #2d 'group' of constraint deleted, i.e. the single constraint y>|0|
                >>> prob.constraints #doctest: +NORMALIZE_WHITESPACE
                [# (1x1)-affine constraint: 〈 |1| | x[0] 〉 < y[0] #,
                 # (1x1)-affine constraint: 〈 |1| | x[2] 〉 < y[2] #,
                 # (1x1)-affine constraint: 〈 |1| | x[3] 〉 < y[3] #,
                 # (2x1)-affine constraint: x[0] < |2.0| #,
                 # (2x1)-affine constraint: x[1] < |2.0| #,
                 # (2x1)-affine constraint: x[2] < |2.0| #,
                 # (2x1)-affine constraint: x[3] < |1| #]
                >>> prob.remove_constraint((2,))                        #3d 'group' of constraint deleted, (originally the 4th group, i.e. x[3]<|1|)
                >>> prob.constraints #doctest: +NORMALIZE_WHITESPACE
                [# (1x1)-affine constraint: 〈 |1| | x[0] 〉 < y[0] #,
                 # (1x1)-affine constraint: 〈 |1| | x[2] 〉 < y[2] #,
                 # (1x1)-affine constraint: 〈 |1| | x[3] 〉 < y[3] #,
                 # (2x1)-affine constraint: x[0] < |2.0| #,
                 # (2x1)-affine constraint: x[1] < |2.0| #,
                 # (2x1)-affine constraint: x[2] < |2.0| #]
                >>> prob.remove_constraint((1,1))                       #2d constraint of the 2d group (originally the 3rd group), i.e. x[1]<|2|
                >>> prob.constraints #doctest: +NORMALIZE_WHITESPACE
                [# (1x1)-affine constraint: 〈 |1| | x[0] 〉 < y[0] #,
                 # (1x1)-affine constraint: 〈 |1| | x[2] 〉 < y[2] #,
                 # (1x1)-affine constraint: 〈 |1| | x[3] 〉 < y[3] #,
                 # (2x1)-affine constraint: x[0] < |2.0| #,
                 # (2x1)-affine constraint: x[2] < |2.0| #]

                
                """
                #TODO    *examples with list of geomeans
                
                self.reset_solver_instances()
                if isinstance(ind,int): #constraint given with its "raw index"
                        cons = self.constraints[ind]
                        if cons.typeOfConstraint[:3]=='lin':
                                self.numberAffConstraints-=(cons.Exp1.size[0]*cons.Exp1.size[1])
                        elif cons.typeOfConstraint[2:]=='cone':
                                self.numberConeVars-=((cons.Exp1.size[0]*cons.Exp1.size[1])+1)
                                self.numberConeConstraints-=1
                                if cons.typeOfConstraint[:2]=='RS':
                                        self.numberConeVars-=1
                        elif cons.typeOfConstraint=='lse':
                                self.numberLSEVars-=(cons.Exp1.size[0]*cons.Exp1.size[1])
                                self.numberLSEConstraints-=1
                        elif cons.typeOfConstraint=='quad':
                                self.numberQuadConstraints-=1
                                self.numberQuadNNZ-=cons.Exp1.nnz()
                        elif cons.typeOfConstraint[:3]=='sdp':
                                self.numberSDPConstraints-=1
                                self.numberSDPVars-=(cons.Exp1.size[0]*(cons.Exp1.size[0]+1))/2
                                if cons.semidefVar:
                                        cons.semidefVar.semiDef = False
                                        
                                      
                        del self.constraints[ind]
                        self.countCons -=1
                        if self.last_updated_constraint > 0:
                                self.last_updated_constraint-=1
                        if ind in self.consNumbering: #single added constraint
                                self.consNumbering.remove(ind)
                                start=ind
                                self.consNumbering=offset_in_lil(self.consNumbering,1,ind)
                        else: #a constraint within a group of constraints
                                for i,l in enumerate(self.consNumbering):
                                        if ind in _flatten([l]):
                                                l0 = l[0]
                                                while isinstance(l0,list): l0=l0[0]
                                                start=l0
                                                _remove_in_lil(self.consNumbering,ind)
                                                
                                self.consNumbering=offset_in_lil(self.consNumbering,1,ind)
                                goc=self.groupsOfConstraints[start]
                                self.groupsOfConstraints[start] = [ goc[0]-1,
                                                                goc[1][:-1]+'{-1cons}\n',
                                                                goc[2]]
                                if goc[0]==start:
                                        del self.groupsOfConstraints[start]
                        #offset in subsequent goc
                        for stidx in self.groupsOfConstraints:
                                if stidx>start:
                                        goc=self.groupsOfConstraints[stidx]
                                        del self.groupsOfConstraints[stidx]
                                        goc[0]=goc[0]-1
                                        self.groupsOfConstraints[stidx-1] = goc
                        return

                indtuple=ind
                lsind=self.consNumbering                
                for k in indtuple:
                        if not isinstance(lsind,list):
                                if k==0:
                                        break
                                else:
                                        raise Exception('too many indices')
                        if k>=len(lsind):
                                raise Exception('index is too large')
                        lsind=lsind[k]
                #now, lsind must be the index or list of indices to remove
                if isinstance(lsind,list): #a list of constraints
                        #we flatten lsind for the case where it is still a list of lists
                        lsind_top = lsind
                        lsind = list(_flatten(lsind))

                        for ind in reversed(lsind):
                                cons = self.constraints[ind]
                                if cons.typeOfConstraint[:3]=='lin':
                                        self.numberAffConstraints-=(cons.Exp1.size[0]*cons.Exp1.size[1])
                                elif cons.typeOfConstraint[2:]=='cone':
                                        self.numberConeVars-=((cons.Exp1.size[0]*cons.Exp1.size[1])+1)
                                        self.numberConeConstraints-=1
                                        if cons.typeOfConstraint[:2]=='RS':
                                                self.numberConeVars-=1
                                elif cons.typeOfConstraint=='lse':
                                        self.numberLSEVars-=(cons.Exp1.size[0]*cons.Exp1.size[1])
                                        self.numberLSEConstraints-=1
                                elif cons.typeOfConstraint=='quad':
                                        self.numberQuadConstraints-=1
                                        self.numberQuadNNZ-=cons.Exp1.nnz()
                                elif cons.typeOfConstraint[:3]=='sdp':
                                        self.numberSDPConstraints-=1
                                        self.numberSDPVars-=(cons.Exp1.size[0]*(cons.Exp1.size[0]+1))/2
                                        
                                        if cons.semidefVar:
                                                cons.semidefVar.semiDef = False
                                del self.constraints[ind]
                        self.countCons -= len(lsind)
                        _remove_in_lil(self.consNumbering,lsind_top)
                        self.consNumbering=offset_in_lil(self.consNumbering,len(lsind),lsind[0])
                        #update this group of constraints
                        for start,goc in self.groupsOfConstraints.iteritems():
                                if lsind[0]>=start and lsind[0]<=goc[0]: break
                        
                        self.groupsOfConstraints[start] = [goc[0]-len(lsind),
                                                           goc[1][:-1]+'{-%dcons}\n'%len(lsind),
                                                           goc[2]]
                        if self.groupsOfConstraints[start][0]<start:
                                        del self.groupsOfConstraints[start]
                        #offset in subsequent goc
                        oldkeys = self.groupsOfConstraints.keys()
                        for stidx in oldkeys:
                                if stidx>start:
                                        goc=self.groupsOfConstraints[stidx]
                                        del self.groupsOfConstraints[stidx]
                                        goc[0]=goc[0]-len(lsind)
                                        self.groupsOfConstraints[stidx-len(lsind)] = goc
                elif isinstance(lsind,int):
                        self.remove_constraint(lsind)

                self._eliminate_useless_variables()
                        
                
        def _eval_all(self):
                """
                Returns the big vector with all variable values,
                in the order induced by sorted(self.variables.keys()).
                """
                xx=cvx.matrix([],(0,1))
                for v in sorted(self.variables.keys()):
                        xx=cvx.matrix([xx,self.variables[v].value[:]])
                return xx

                
        def check_current_value_feasibility(self,tol=1e-5):
                """
                returns ``True`` if the
                current value of the variabless
                is a feasible solution, up to the
                tolerance ``tol``. If ``tol`` is set to ``None``,
                the option parameter ``options['tol']`` is used instead.
                The integer feasibility is checked with a tolerance of 1e-3.
                """
                if tol is None:
                        if not(self.options['feastol'] is None):
                                tol = self.options['feastol']
                        else:
                                tol = self.options['tol']
                for cs in self.constraints:
                        sl=cs.slack
                        if not(isinstance(sl,cvx.matrix) or isinstance(sl,cvx.spmatrix)):
                                sl=cvx.matrix(sl)
                        if cs.typeOfConstraint.startswith('sdp'):
                                #check symmetry
                                if min(sl-sl.T)<-tol:
                                        return False
                                if min(sl.T-sl)<-tol:
                                        return False
                                #check positive semidefiniteness
                                if isinstance(sl,cvx.spmatrix):
                                        sl=cvx.matrix(sl)
                                sl=np.array(sl)
                                eg=np.linalg.eigvalsh(sl)
                                if min(eg)<-tol:
                                        return False
                        else:
                                if min(sl)<-tol:
                                        return False
                #integer feasibility
                if not(self.is_continuous()):
                        for vnam,v in self.variables.iteritems():
                                if v.vtype in ('binary','integer'):
                                        sl=v.value
                                        dsl=[min(s-int(s),int(s)+1-s) for s in sl]
                                        if max(dsl)>1e-3:
                                                return False
                                
                #so OK, it's feasible
                return True
                                
                
        """
        ----------------------------------------------------------------
        --                BUILD THE VARIABLES FOR A SOLVER            --
        ----------------------------------------------------------------
        """        

        #GUROBI
        def _make_gurobi_instance_old(self):
                """
                defines the variables gurobi_Instance and grbvar
                """
                             
                try:
                        import gurobipy as grb
                except:
                        raise ImportError('gurobipy not found')
                
                grb_type = {    'continuous' : grb.GRB.CONTINUOUS, 
                                'binary' :     grb.GRB.BINARY, 
                                'integer' :    grb.GRB.INTEGER, 
                                'semicont' :   grb.GRB.SEMICONT, 
                                'semiint' :    grb.GRB.SEMIINT,
                                'symmetric': grb.GRB.CONTINUOUS}
                
                #TODO: onlyChangeObjective
                
                if (self.last_updated_constraint == 0 or
                    self.gurobi_Instance is None):
                        m = grb.Model()
                        self.last_updated_constraint = 0
                        only_update = False
                else:
                        m = self.gurobi_Instance
                        only_update = True
                
                if self.objective[0] == 'max':
                        m.ModelSense = grb.GRB.MAXIMIZE
                else:
                        m.ModelSense = grb.GRB.MINIMIZE
                
                self.options._set('solver','gurobi')
                
                
                #create new variable and quad constraints to handle socp
                tmplhs=[]
                tmprhs=[]
                icone =0
                if only_update:
                        offset_cone = len([1 for v in m.getVars() if '__tmprhs' in v.VarName])
                        offset_supvars = m.NumVars - self.numberOfVars -1
                else:
                        offset_cone = 0
                        offset_supvars = 0
                
                newcons={}
                newvars=[]
                #TODO rewrite interface to cone functions without temporary variables ?
                #     or at least make it correctly with 'passed', so remove_variable is never called
                if self.numberConeConstraints > 0 :
                        for constrKey,constr in enumerate(self.constraints[self.last_updated_constraint:]):
                                if constr.typeOfConstraint[2:]=='cone':
                                        if icone == 0: #first conic constraint
                                                if '__noconstant__' in self.variables:
                                                        noconstant=self.get_variable('__noconstant__')
                                                else:
                                                        noconstant=self.add_variable(
                                                                '__noconstant__',1)
                                                        newvars.append(('__noconstant__',1))
                                                newcons['noconstant']=(noconstant>0)
                                                #no variable shift -> same noconstant var as before
                                if constr.typeOfConstraint=='SOcone':
                                        if '__tmplhs[{0}]__'.format(constrKey) in self.variables:
                                                self.remove_variable('__tmplhs[{0}]__'.format(constrKey)) #constrKey replaced the icone+offset_cone of previous version
                                        if '__tmprhs[{0}]__'.format(constrKey) in self.variables:
                                                self.remove_variable('__tmprhs[{0}]__'.format(constrKey))
                                        tmplhs.append(self.add_variable(
                                                '__tmplhs[{0}]__'.format(constrKey),
                                                constr.Exp1.size))
                                        tmprhs.append(self.add_variable(
                                                '__tmprhs[{0}]__'.format(constrKey),
                                                1))
                                        newvars.append(('__tmplhs[{0}]__'.format(constrKey),
                                                constr.Exp1.size[0]*constr.Exp1.size[1]))
                                        newvars.append(('__tmprhs[{0}]__'.format(constrKey),
                                                1))
                                        #v_cons is 0/1/-1 to avoid constants in cone (problem with duals)
                                        v_cons = cvx.matrix( [np.sign(constr.Exp1.constant[i])
                                                                        if constr.Exp1[i].isconstant() else 0
                                                                        for i in range(constr.Exp1.size[0]*constr.Exp1.size[1])],
                                                                        constr.Exp1.size)
                                        #lhs and rhs of the cone constraint
                                        newcons['tmp_lhs_{0}'.format(constrKey)]=(
                                                        constr.Exp1+v_cons*noconstant == tmplhs[-1])
                                        newcons['tmp_rhs_{0}'.format(constrKey)]=(
                                                        constr.Exp2-noconstant == tmprhs[-1])
                                        #conic constraints
                                        newcons['tmp_conesign_{0}'.format(constrKey)]=(
                                                        tmprhs[-1]>0)
                                        newcons['tmp_conequad_{0}'.format(constrKey)]=(
                                        -tmprhs[-1]**2+(tmplhs[-1]|tmplhs[-1])<0)
                                        icone+=1
                                if constr.typeOfConstraint=='RScone':
                                        if '__tmplhs[{0}]__'.format(constrKey) in self.variables:
                                                self.remove_variable('__tmplhs[{0}]__'.format(constrKey))
                                        if '__tmprhs[{0}]__'.format(constrKey) in self.variables:
                                                self.remove_variable('__tmprhs[{0}]__'.format(constrKey))
                                        tmplhs.append(self.add_variable(
                                                '__tmplhs[{0}]__'.format(constrKey),
                                                (constr.Exp1.size[0]*constr.Exp1.size[1])+1
                                                ))
                                        tmprhs.append(self.add_variable(
                                                '__tmprhs[{0}]__'.format(constrKey),
                                                1))
                                        newvars.append(('__tmplhs[{0}]__'.format(constrKey),
                                                (constr.Exp1.size[0]*constr.Exp1.size[1])+1))
                                        newvars.append(('__tmprhs[{0}]__'.format(constrKey),
                                                1))
                                        #v_cons is 0/1/-1 to avoid constants in cone (problem with duals)
                                        expcat = ((2*constr.Exp1[:]) // (constr.Exp2-constr.Exp3))
                                        v_cons = cvx.matrix( [np.sign(expcat.constant[i])
                                                                        if expcat[i].isconstant() else 0
                                                                        for i in range(expcat.size[0]*expcat.size[1])],
                                                                        expcat.size)
                                        
                                        #lhs and rhs of the cone constraint
                                        newcons['tmp_lhs_{0}'.format(constrKey)]=(
                                        (2*constr.Exp1[:] // (constr.Exp2-constr.Exp3)) + v_cons*noconstant == tmplhs[-1])
                                        newcons['tmp_rhs_{0}'.format(constrKey)]=(
                                                constr.Exp2+constr.Exp3 - noconstant == tmprhs[-1])
                                        #conic constraints
                                        newcons['tmp_conesign_{0}'.format(constrKey)]=(
                                                        tmprhs[-1]>0)
                                        newcons['tmp_conequad_{0}'.format(constrKey)]=(
                                        -tmprhs[-1]**2+(tmplhs[-1]|tmplhs[-1])<0)
                                        icone+=1
                        #variable shift
                        for tv in tmprhs+tmplhs:
                                tv._startIndex+=offset_supvars
                                tv._endIndex+=offset_supvars
                
                                
                #variables
                
               
                if (self.options['verbose']>1) and (not only_update):
                        limitbar=self.numberOfVars
                        prog = ProgressBar(0,limitbar, None, mode='fixed')
                        oldprog = str(prog)
                        print('Creating variables...')
                        print
                
                if only_update:
                        supvars=_bsum([nv[1] for nv in newvars])
                        x=self.grbvar
                        for kvar,sz in newvars:
                                for kj in range(sz):
                                        name = kvar+'_'+str(kj)
                                        x.append( m.addVar(obj = 0.,
                                                name = name,
                                                vtype = grb_type['continuous'],
                                                lb = -grb.GRB.INFINITY))
                else:
                        
                        x=[]
                        if self.objective[1] is None:
                                objective = {}
                        elif isinstance(self.objective[1],QuadExp):
                                objective = self.objective[1].aff.factors
                        elif isinstance(self.objective[1],AffinExp):
                                objective = self.objective[1].factors
                        
                        for kvar,variable in self.variables.iteritems():
                                sj=variable.startIndex
                                varsize = variable.endIndex-sj
                                if objective.has_key(variable):
                                        vectorObjective = objective[variable]
                                else:
                                        vectorObjective = [0]*(varsize)
                                if variable.is_valued() and self.options['hotstart']:
                                        vstart = variable.value
                                for k in range(varsize):
                                        name=kvar+'_'+str(k)
                                        x.append( m.addVar(obj = vectorObjective[k],
                                                           name = name,
                                                           vtype = grb_type[variable.vtype],
                                                           lb = -grb.GRB.INFINITY))
                                        if variable.is_valued() and self.options['hotstart']:
                                                x[-1].Start = vstart[k]
                                                           
                                        if self.options['verbose']>1:
                                                #<--display progress
                                                prog.increment_amount()
                                                if oldprog != str(prog):
                                                        print prog, "\r",
                                                        sys.stdout.flush()
                                                        oldprog=str(prog)
                                                #-->
                        
                        if self.options['verbose']>1:
                                prog.update_amount(limitbar)
                                print prog, "\r",
                                print
                
                
                        #quad part of the objective
                        if isinstance(self.objective[1],QuadExp):
                                m.update()
                                lpart = m.getObjective()
                                qd=self.objective[1].quad
                                qind1,qind2,qval=[],[],[]
                                for i,j in qd:
                                        fact=qd[i,j]
                                        namei=i.name
                                        namej=j.name
                                        si=i.startIndex
                                        sj=j.startIndex
                                        if (j,i) in qd: #quad stores x'*A1*y + y'*A2*x
                                                if si<sj:
                                                        fact+=qd[j,i].T
                                                elif si>sj:
                                                        fact=cvx.sparse([0])
                                                elif si==sj:
                                                        pass
                                        qind1.extend([namei+'_'+str(k) for k in fact.I])
                                        qind2.extend([namej+'_'+str(k) for k in fact.J])
                                        qval.extend(fact.V)
                                q_exp=grb.quicksum([f*m.getVarByName(n1) * m.getVarByName(n2) for (f,n1,n2) in zip(qval,qind1,qind2)])
                                m.setObjective(q_exp+lpart)
                                
                m.update()
                #constraints
                
                #progress bar
                if self.options['verbose']>0:
                        print
                        print('adding constraints...')
                        print 
                if self.options['verbose']>1:
                        limitbar= (self.numberAffConstraints +
                                   self.numberQuadConstraints +
                                   len(newcons) -
                                   self.last_updated_constraint)
                        prog = ProgressBar(0,limitbar, None, mode='fixed')
                        oldprog = str(prog)
                
                if only_update:
                        boundcons=self.grb_boundcons
                else:
                        boundcons={} #dictionary of i,j,b,v for bound constraints
                
                #join all constraints
                def join_iter(it1,it2):
                        for i in it1: yield i
                        for i in it2: yield i
                        
                allcons = join_iter(enumerate(self.constraints[self.last_updated_constraint:]),
                                    newcons.iteritems())
                
                irow=0
                for constrKey,constr in allcons:
                        
                        if constr.typeOfConstraint[:3] == 'lin':
                                #init of boundcons[key]
                                if isinstance(constrKey,int):
                                        offsetkey=self.last_updated_constraint+constrKey
                                else:
                                        offsetkey=constrKey
                                boundcons[offsetkey]=[]
                                
                                #parse the (i,j,v) triple
                                ijv=[]
                                for var,fact in (constr.Exp1-constr.Exp2).factors.iteritems():
                                        if type(fact)!=cvx.base.spmatrix:
                                                fact = cvx.sparse(fact)
                                        ijv.extend(zip( fact.I,
                                                [var.name+'_'+str(j) for j in fact.J],
                                                fact.V))
                                ijvs=sorted(ijv)
                                
                                itojv={}
                                lasti=-1
                                for (i,j,v) in ijvs:
                                        if i==lasti:
                                                itojv[i].append((j,v))
                                        else:
                                                lasti=i
                                                itojv[i]=[(j,v)]
                                
                                #constant term
                                szcons = constr.Exp1.size[0]*constr.Exp1.size[1]
                                rhstmp = cvx.matrix(0.,(szcons,1))
                                constant1 = constr.Exp1.constant #None or a 1*1 matrix
                                constant2 = constr.Exp2.constant
                                if not constant1 is None:
                                        rhstmp = rhstmp-constant1
                                if not constant2 is None:
                                        rhstmp = rhstmp+constant2
                                                                
                                for i,jv in itojv.iteritems():
                                        r=rhstmp[i]
                                        if len(jv)==1:
                                                #BOUND
                                                name,v=jv[0]
                                                xj=m.getVarByName(name)
                                                b=r/float(v)
                                                if v>0:
                                                        if constr.typeOfConstraint[:4] in ['lin<','lin=']:
                                                                if b<xj.ub:
                                                                        xj.ub=b
                                                        if constr.typeOfConstraint[:4] in ['lin>','lin=']:
                                                                if b>xj.lb:
                                                                        xj.lb=b
                                                else:#v<0
                                                        if constr.typeOfConstraint[:4] in ['lin<','lin=']:
                                                                if b>xj.lb:
                                                                        xj.lb=b
                                                        if constr.typeOfConstraint[:4] in ['lin>','lin=']:
                                                                if b<xj.ub:
                                                                        xj.ub=b
                                                if constr.typeOfConstraint[3]=='=': 
                                                        b='='
                                                boundcons[offsetkey].append((i,name,b,v))
                                        else:
                                                LEXP = grb.LinExpr(
                                                        [v for j,v in jv],
                                                        [m.getVarByName(name) for name,v in jv])
                                                name='lin'+str(offsetkey)+'_'+str(i)
                                                if constr.typeOfConstraint[:4] == 'lin<':
                                                        m.addConstr(LEXP <= r,name=name)
                                                elif constr.typeOfConstraint[:4] == 'lin>':
                                                        m.addConstr(LEXP >= r,name=name)
                                                elif constr.typeOfConstraint[:4] == 'lin=':
                                                        m.addConstr(LEXP == r,name=name)
                                                
                                                irow+=1
                                                
                                        if self.options['verbose']>1:
                                                #<--display progress
                                                prog.increment_amount()
                                                if oldprog != str(prog):
                                                        print prog, "\r",
                                                        sys.stdout.flush()
                                                        oldprog=str(prog)
                                                #-->                                                
                        
                        
                        elif constr.typeOfConstraint == 'quad':
                                if isinstance(constrKey,int):
                                        offsetkey=self.last_updated_constraint+constrKey
                                else:
                                        offsetkey=constrKey
                                #quad part
                                qind1,qind2,qval=[],[],[]
                                qd=constr.Exp1.quad
                                q_exp= 0.
                                for i,j in qd:
                                        fact=qd[i,j]
                                        namei=i.name
                                        namej=j.name
                                        si=i.startIndex
                                        sj=j.startIndex
                                        if (j,i) in qd: #quad stores x'*A1*y + y'*A2*x
                                                if si<sj:
                                                        fact+=qd[j,i].T
                                                elif si>sj:
                                                        fact=cvx.sparse([0])
                                                elif si==sj:
                                                        pass
                                        qind1.extend([namei+'_'+str(k) for k in fact.I])
                                        qind2.extend([namej+'_'+str(k) for k in fact.J])
                                        qval.extend(fact.V)
                                q_exp=grb.quicksum([f*m.getVarByName(n1) * m.getVarByName(n2) for (f,n1,n2) in zip(qval,qind1,qind2)])
                                #lin part
                                lind,lval=[],[]
                                af=constr.Exp1.aff.factors
                                for var in af:
                                        name = var.name
                                        lind.extend([name+'_'+str(k) for k in af[var].J])
                                        lval.extend(af[var].V)
                                l_exp=grb.LinExpr(
                                        lval,
                                        [m.getVarByName(name) for name in lind])
                                #constant
                                qcs=0.
                                if not(constr.Exp1.aff.constant is None):
                                        qcs = - constr.Exp1.aff.constant[0]
                                m.addQConstr(q_exp + l_exp <= qcs )
                                
                                if self.options['verbose']>1:
                                        #<--display progress
                                        prog.increment_amount()
                                        if oldprog != str(prog):
                                                print prog, "\r",
                                                sys.stdout.flush()
                                                oldprog=str(prog)
                                        #-->
                                
                        elif constr.typeOfConstraint[2:] == 'cone':
                                offsetkey=self.last_updated_constraint+constrKey
                                boundcons[offsetkey]=[]
                                #will be handled in the newcons dictionary
                                
                        else:
                                raise Exception('type of constraint not handled (yet ?) for cplex:{0}'.format(
                                        constr.typeOfConstraint))
                        
                       

                if self.options['verbose']>1:
                        prog.update_amount(limitbar)
                        print prog, "\r",
                        print
                        
                m.update()
                
                self.gurobi_Instance=m
                self.grbvar=x
                self.grb_boundcons=boundcons
                
                if 'noconstant' in newcons or len(tmplhs)>0:
                        self._remove_temporary_variables()
                
                if self.options['verbose']>0:
                        print 'Gurobi instance created'
                        print
                                
        def _make_gurobi_instance(self):
                """
                defines the variables gurobi_Instance and grbvar
                """
                             
                try:
                        import gurobipy as grb
                except:
                        raise ImportError('gurobipy not found')
                
                grb_type = {    'continuous' : grb.GRB.CONTINUOUS, 
                                'binary' :     grb.GRB.BINARY, 
                                'integer' :    grb.GRB.INTEGER, 
                                'semicont' :   grb.GRB.SEMICONT, 
                                'semiint' :    grb.GRB.SEMIINT,
                                'symmetric': grb.GRB.CONTINUOUS}
                
                #TODO: onlyChangeObjective
                
                if (self.gurobi_Instance is None):
                        m = grb.Model()
                        boundcons = {}
                else:
                        m = self.gurobi_Instance
                        boundcons = self.grb_boundcons
                
                if self.objective[0] == 'max':
                        m.ModelSense = grb.GRB.MAXIMIZE
                else:
                        m.ModelSense = grb.GRB.MINIMIZE
                
                self.options._set('solver','gurobi')
                
                
                #create new variable and quad constraints to handle socp
                tmplhs=[]
                tmprhs=[]
                icone =0
                
                NUMVAR_OLD = m.numVars #total number of vars before
                NUMVAR0_OLD = int(_bsum([(var.endIndex-var.startIndex) #old number of vars without cone vars
                        for var in self.variables.values()
                        if ('gurobi' in var.passed)]))
                OFFSET_CV = NUMVAR_OLD - NUMVAR0_OLD # number of conevars already there. 
                NUMVAR0_NEW = int(_bsum([(var.endIndex-var.startIndex)#new vars without new cone vars
                        for var in self.variables.values()
                        if not('gurobi' in var.passed)]))
                
                
                newcons={}
                newvars=[]
                if self.numberConeConstraints > 0 :
                        for constrKey,constr in enumerate(self.constraints):
                                if 'gurobi' in constr.passed:
                                        continue
                                if constr.typeOfConstraint[2:]=='cone':
                                        if icone == 0: #first conic constraint
                                                if '__noconstant__' in self.variables:
                                                        noconstant=self.get_variable('__noconstant__')
                                                else:
                                                        noconstant=self.add_variable(
                                                                '__noconstant__',1)
                                                        newvars.append(('__noconstant__',1))
                                                newcons['noconstant']=(noconstant>0)
                                                #no variable shift -> same noconstant var as before
                                if constr.typeOfConstraint=='SOcone':
                                        if '__tmplhs[{0}]__'.format(constrKey) in self.variables:
                                                # remove_variable should never called (we let it for security)
                                                self.remove_variable('__tmplhs[{0}]__'.format(constrKey)) #constrKey replaced the icone+offset_cone of previous version
                                        if '__tmprhs[{0}]__'.format(constrKey) in self.variables:
                                                self.remove_variable('__tmprhs[{0}]__'.format(constrKey))
                                        tmplhs.append(self.add_variable(
                                                '__tmplhs[{0}]__'.format(constrKey),
                                                constr.Exp1.size))
                                        tmprhs.append(self.add_variable(
                                                '__tmprhs[{0}]__'.format(constrKey),
                                                1))
                                        newvars.append(('__tmplhs[{0}]__'.format(constrKey),
                                                constr.Exp1.size[0]*constr.Exp1.size[1]))
                                        newvars.append(('__tmprhs[{0}]__'.format(constrKey),
                                                1))
                                        #v_cons is 0/1/-1 to avoid constants in cone (problem with duals)
                                        v_cons = cvx.matrix( [np.sign(constr.Exp1.constant[i])
                                                                        if constr.Exp1[i].isconstant() else 0
                                                                        for i in range(constr.Exp1.size[0]*constr.Exp1.size[1])],
                                                                        constr.Exp1.size)
                                        #lhs and rhs of the cone constraint
                                        newcons['tmp_lhs_{0}'.format(constrKey)]=(
                                                        constr.Exp1+v_cons*noconstant == tmplhs[-1])
                                        newcons['tmp_rhs_{0}'.format(constrKey)]=(
                                                        constr.Exp2-noconstant == tmprhs[-1])
                                        #conic constraints
                                        newcons['tmp_conesign_{0}'.format(constrKey)]=(
                                                        tmprhs[-1]>0)
                                        newcons['tmp_conequad_{0}'.format(constrKey)]=(
                                        -tmprhs[-1]**2+(tmplhs[-1]|tmplhs[-1])<0)
                                        icone+=1
                                if constr.typeOfConstraint=='RScone':
                                        if '__tmplhs[{0}]__'.format(constrKey) in self.variables:
                                                self.remove_variable('__tmplhs[{0}]__'.format(constrKey))
                                        if '__tmprhs[{0}]__'.format(constrKey) in self.variables:
                                                self.remove_variable('__tmprhs[{0}]__'.format(constrKey))
                                        tmplhs.append(self.add_variable(
                                                '__tmplhs[{0}]__'.format(constrKey),
                                                (constr.Exp1.size[0]*constr.Exp1.size[1])+1
                                                ))
                                        tmprhs.append(self.add_variable(
                                                '__tmprhs[{0}]__'.format(constrKey),
                                                1))
                                        newvars.append(('__tmplhs[{0}]__'.format(constrKey),
                                                (constr.Exp1.size[0]*constr.Exp1.size[1])+1))
                                        newvars.append(('__tmprhs[{0}]__'.format(constrKey),
                                                1))
                                        #v_cons is 0/1/-1 to avoid constants in cone (problem with duals)
                                        expcat = ((2*constr.Exp1[:]) // (constr.Exp2-constr.Exp3))
                                        v_cons = cvx.matrix( [np.sign(expcat.constant[i])
                                                                        if expcat[i].isconstant() else 0
                                                                        for i in range(expcat.size[0]*expcat.size[1])],
                                                                        expcat.size)
                                        
                                        #lhs and rhs of the cone constraint
                                        newcons['tmp_lhs_{0}'.format(constrKey)]=(
                                        (2*constr.Exp1[:] // (constr.Exp2-constr.Exp3)) + v_cons*noconstant == tmplhs[-1])
                                        newcons['tmp_rhs_{0}'.format(constrKey)]=(
                                                constr.Exp2+constr.Exp3 - noconstant == tmprhs[-1])
                                        #conic constraints
                                        newcons['tmp_conesign_{0}'.format(constrKey)]=(
                                                        tmprhs[-1]>0)
                                        newcons['tmp_conequad_{0}'.format(constrKey)]=(
                                        -tmprhs[-1]**2+(tmplhs[-1]|tmplhs[-1])<0)
                                        icone+=1

                NUMVAR_NEW = int(_bsum([(var.endIndex-var.startIndex)#new vars including cone vars
                        for var in self.variables.values()
                        if not('gurobi' in var.passed)]))
               
                NUMVAR = NUMVAR_OLD + NUMVAR_NEW#total number of variables (including extra vars for cones)
                
                                        
                #variables
                
               
                if (self.options['verbose']>1) and NUMVAR_NEW>0:
                        limitbar=NUMVAR_NEW
                        prog = ProgressBar(0,limitbar, None, mode='fixed')
                        oldprog = str(prog)
                        print('Creating variables...')
                        print
                
                if NUMVAR_NEW:
                        
                        x=[]#list of new vars

                        ub={j:grb.GRB.INFINITY for j in range(NUMVAR_OLD,NUMVAR)}
                        lb={j:-grb.GRB.INFINITY for j in range(NUMVAR_OLD,NUMVAR)}
                        
                        for kvar,variable in [(kvar,variable) for (kvar,variable)
                                                in self.variables.iteritems()
                                                if 'gurobi' not in variable.passed]:
                                
                                variable.gurobi_startIndex=variable.startIndex + OFFSET_CV
                                variable.gurobi_endIndex  =variable.endIndex + OFFSET_CV
                                sj=variable.gurobi_startIndex
                                ej=variable.gurobi_endIndex
                                
                                for ind,(lo,up) in variable.bnd.iteritems():
                                      if not(lo is None):
                                              lb[sj+ind]=lo
                                      if not(up is None):
                                              ub[sj+ind]=up
                        
                        vartopass = sorted([(variable.gurobi_startIndex,variable) for (kvar,variable)
                                                in self.variables.iteritems()
                                                if 'gurobi' not in variable.passed])
                        
                        
                        for (vcsi,variable) in vartopass:
                                variable.passed.append('gurobi')
                                sj = variable.gurobi_startIndex
                                tp = variable.vtype
                                varsize = variable.endIndex-variable.startIndex
                                
                              
                                for k in range(varsize):
                                        name=variable.name+'_'+str(k)
                                        x.append( m.addVar(obj = 0,
                                                           name = name,
                                                           vtype = grb_type[tp],
                                                           lb = lb[sj+k],
                                                           ub = ub[sj+k]))

                                                           
                                        if self.options['verbose']>1:
                                                #<--display progress
                                                prog.increment_amount()
                                                if oldprog != str(prog):
                                                        print prog, "\r",
                                                        sys.stdout.flush()
                                                        oldprog=str(prog)
                                                #-->
                        
                        if self.options['verbose']>1:
                                prog.update_amount(limitbar)
                                print prog, "\r",
                                print
                
                m.update()
                #parse all vars for hotstart
                if self.options['hotstart']:
                        for kvar,variable in self.variables.iteritems():
                                if variable.is_valued():
                                        vstart = variable.value
                                        varsize = variable.endIndex-variable.startIndex
                                        for k in range(varsize):
                                                name = kvar+'_'+str(k)
                                                xj=m.getVarByName(name)
                                                xj.Start= vstart[k]
                m.update()
                
                #parse all variable for the obective (only if not obj_passed)
                if 'gurobi' not in self.obj_passed:
                        self.obj_passed.append('gurobi')
                        if self.objective[1] is None:
                                objective = {}
                        elif isinstance(self.objective[1],QuadExp):
                                objective = self.objective[1].aff.factors
                        elif isinstance(self.objective[1],AffinExp):
                                objective = self.objective[1].factors
                        
                        m.set_objective(0)
                        m.update()
                        
                        for variable,vect in objective.iteritems():
                                varsize = variable.endIndex-variable.startIndex
                                for (k,v) in zip(vect.J,vect.V):
                                        name = variable.name+'_'+str(k)
                                        xj=m.getVarByName(name)
                                        xj.obj = v
                        
                        m.update()
                        
                        #quad part of the objective
                        if isinstance(self.objective[1],QuadExp):
                                lpart = m.getObjective()
                                qd=self.objective[1].quad
                                qind1,qind2,qval=[],[],[]
                                for i,j in qd:
                                        fact=qd[i,j]
                                        namei=i.name
                                        namej=j.name
                                        si=i.startIndex
                                        sj=j.startIndex
                                        if (j,i) in qd: #quad stores x'*A1*y + y'*A2*x
                                                if si<sj:
                                                        fact+=qd[j,i].T
                                                elif si>sj:
                                                        fact=cvx.sparse([0])
                                                elif si==sj:
                                                        pass
                                        qind1.extend([namei+'_'+str(k) for k in fact.I])
                                        qind2.extend([namej+'_'+str(k) for k in fact.J])
                                        qval.extend(fact.V)
                                q_exp=grb.quicksum([f*m.getVarByName(n1) * m.getVarByName(n2) for (f,n1,n2) in zip(qval,qind1,qind2)])
                                m.setObjective(q_exp+lpart)
                                m.update()
                                        
                        
                #constraints
                
                NUMCON_NEW = int(_bsum([(cs.Exp1.size[0] * cs.Exp1.size[1])
                                        for cs in self.constraints
                                        if (cs.typeOfConstraint.startswith('lin'))
                                        and not('gurobi' in cs.passed)] +
                                        [1 for cs in self.constraints
                                        if (cs.typeOfConstraint=='quad')
                                        and not('gurobi' in cs.passed)]
                                       )
                                )
                
                #progress bar
                if self.options['verbose']>0:
                        print
                        print('adding constraints...')
                        print 
                if self.options['verbose']>1:
                        limitbar= NUMCON_NEW
                        prog = ProgressBar(0,limitbar, None, mode='fixed')
                        oldprog = str(prog)
                
              
                
                #join all constraints
                def join_iter(it1,it2):
                        for i in it1: yield i
                        for i in it2: yield i
                        
                allcons = join_iter(enumerate(self.constraints),
                                    newcons.iteritems())
                
                irow=0
                for constrKey,constr in allcons:
                        if 'gurobi' in constr.passed:
                                continue
                        else:
                                constr.passed.append('gurobi')
                        
                        if constr.typeOfConstraint[:3] == 'lin':
                                #init of boundcons[key]
                                boundcons[constrkey]=[]
                                
                                #parse the (i,j,v) triple
                                ijv=[]
                                for var,fact in (constr.Exp1-constr.Exp2).factors.iteritems():
                                        if type(fact)!=cvx.base.spmatrix:
                                                fact = cvx.sparse(fact)
                                        ijv.extend(zip( fact.I,
                                                [var.name+'_'+str(j) for j in fact.J],
                                                fact.V))
                                ijvs=sorted(ijv)
                                
                                itojv={}
                                lasti=-1
                                for (i,j,v) in ijvs:
                                        if i==lasti:
                                                itojv[i].append((j,v))
                                        else:
                                                lasti=i
                                                itojv[i]=[(j,v)]
                                
                                #constant term
                                szcons = constr.Exp1.size[0]*constr.Exp1.size[1]
                                rhstmp = cvx.matrix(0.,(szcons,1))
                                constant1 = constr.Exp1.constant #None or a 1*1 matrix
                                constant2 = constr.Exp2.constant
                                if not constant1 is None:
                                        rhstmp = rhstmp-constant1
                                if not constant2 is None:
                                        rhstmp = rhstmp+constant2
                                                                
                                for i,jv in itojv.iteritems():
                                        r=rhstmp[i]
                                        if len(jv)==1:
                                                #BOUND
                                                name,v=jv[0]
                                                xj=m.getVarByName(name)
                                                b=r/float(v)
                                                if v>0:
                                                        if constr.typeOfConstraint[:4] in ['lin<','lin=']:
                                                                if b<xj.ub:
                                                                        xj.ub=b
                                                        if constr.typeOfConstraint[:4] in ['lin>','lin=']:
                                                                if b>xj.lb:
                                                                        xj.lb=b
                                                else:#v<0
                                                        if constr.typeOfConstraint[:4] in ['lin<','lin=']:
                                                                if b>xj.lb:
                                                                        xj.lb=b
                                                        if constr.typeOfConstraint[:4] in ['lin>','lin=']:
                                                                if b<xj.ub:
                                                                        xj.ub=b
                                                if constr.typeOfConstraint[3]=='=': 
                                                        b='='
                                                boundcons[constrKey].append((i,name,b,v))
                                        else:
                                                LEXP = grb.LinExpr(
                                                        [v for j,v in jv],
                                                        [m.getVarByName(name) for name,v in jv])
                                                name='lin'+str(constrKey)+'_'+str(i)
                                                if constr.typeOfConstraint[:4] == 'lin<':
                                                        m.addConstr(LEXP <= r,name=name)
                                                elif constr.typeOfConstraint[:4] == 'lin>':
                                                        m.addConstr(LEXP >= r,name=name)
                                                elif constr.typeOfConstraint[:4] == 'lin=':
                                                        m.addConstr(LEXP == r,name=name)
                                                
                                                irow+=1
                                                
                                        if self.options['verbose']>1:
                                                #<--display progress
                                                prog.increment_amount()
                                                if oldprog != str(prog):
                                                        print prog, "\r",
                                                        sys.stdout.flush()
                                                        oldprog=str(prog)
                                                #-->                                                
                        
                        
                        elif constr.typeOfConstraint == 'quad':
                                #quad part
                                qind1,qind2,qval=[],[],[]
                                qd=constr.Exp1.quad
                                q_exp= 0.
                                for i,j in qd:
                                        fact=qd[i,j]
                                        namei=i.name
                                        namej=j.name
                                        si=i.startIndex
                                        sj=j.startIndex
                                        if (j,i) in qd: #quad stores x'*A1*y + y'*A2*x
                                                if si<sj:
                                                        fact+=qd[j,i].T
                                                elif si>sj:
                                                        fact=cvx.sparse([0])
                                                elif si==sj:
                                                        pass
                                        qind1.extend([namei+'_'+str(k) for k in fact.I])
                                        qind2.extend([namej+'_'+str(k) for k in fact.J])
                                        qval.extend(fact.V)
                                q_exp=grb.quicksum([f*m.getVarByName(n1) * m.getVarByName(n2) for (f,n1,n2) in zip(qval,qind1,qind2)])
                                #lin part
                                lind,lval=[],[]
                                af=constr.Exp1.aff.factors
                                for var in af:
                                        name = var.name
                                        lind.extend([name+'_'+str(k) for k in af[var].J])
                                        lval.extend(af[var].V)
                                l_exp=grb.LinExpr(
                                        lval,
                                        [m.getVarByName(name) for name in lind])
                                #constant
                                qcs=0.
                                if not(constr.Exp1.aff.constant is None):
                                        qcs = - constr.Exp1.aff.constant[0]
                                m.addQConstr(q_exp + l_exp <= qcs )
                                
                                if self.options['verbose']>1:
                                        #<--display progress
                                        prog.increment_amount()
                                        if oldprog != str(prog):
                                                print prog, "\r",
                                                sys.stdout.flush()
                                                oldprog=str(prog)
                                        #-->
                                
                        elif constr.typeOfConstraint[2:] == 'cone':
                                boundcons[constrKey]=[]
                                #will be handled in the newcons dictionary
                                
                        else:
                                raise Exception('type of constraint not handled (yet ?) for gurobi:{0}'.format(
                                        constr.typeOfConstraint))
                        
                       

                if self.options['verbose']>1:
                        prog.update_amount(limitbar)
                        print prog, "\r",
                        print
                        
                m.update()
                
                self.gurobi_Instance=m
                self.grbvar.extend(x)
                self.grb_boundcons=boundcons
                
                if 'noconstant' in newcons or len(tmplhs)>0:
                        self._remove_temporary_variables()
                
                if self.options['verbose']>0:
                        print 'Gurobi instance created'
                        print                                
                                
        def is_continuous(self):
                """ Returns ``True`` if there are only continuous variables"""
                for kvar in self.variables.keys():
                        if self.variables[kvar].vtype not in ['continuous','symmetric']:
                                return False
                return True
                
                
        def _make_cplex_instance(self):
                """
                Defines the variables cplex_Instance and cplexvar,
                used by the cplex solver.
                """
                try:
                        import cplex
                except:
                        raise ImportError('cplex library not found')
                
                import itertools
                
                if (self.cplex_Instance is None):
                        c = cplex.Cplex()
                        boundcons={}

                else:
                        c = self.cplex_Instance
                        boundcons=self.cplex_boundcons
                
                sense_opt = self.objective[0]
                if sense_opt == 'max':
                        c.objective.set_sense(c.objective.sense.maximize)
                elif sense_opt == 'min':
                        c.objective.set_sense(c.objective.sense.minimize)
                
                self.set_option('solver','cplex')
                
                cplex_type = {  'continuous' : c.variables.type.continuous, 
                                'binary' : c.variables.type.binary, 
                                'integer' : c.variables.type.integer, 
                                'semicont' : c.variables.type.semi_continuous, 
                                'semiint' : c.variables.type.semi_integer,
                                'symmetric': c.variables.type.continuous}                
                
                #create new variables and quad constraints to handle socp
                tmplhs=[]
                tmprhs=[]
                icone =0
                
                
                NUMVAR_OLD = c.variables.get_num() #total number of vars before
                NUMVAR0_OLD = int(_bsum([(var.endIndex-var.startIndex) #old number of vars without cone vars
                        for var in self.variables.values()
                        if ('cplex' in var.passed)]))
                OFFSET_CV = NUMVAR_OLD - NUMVAR0_OLD # number of conevars already there. 
                NUMVAR0_NEW = int(_bsum([(var.endIndex-var.startIndex)#new vars without new cone vars
                        for var in self.variables.values()
                        if not('cplex' in var.passed)]))
                        
                
                newcons={}
                newvars=[]
                if self.numberConeConstraints > 0 :
                        for constrKey,constr in enumerate(self.constraints):
                                if 'cplex' in constr.passed:
                                        continue
                                if constr.typeOfConstraint[2:]=='cone':
                                        if icone == 0: #first conic constraint
                                                if '__noconstant__' in self.variables:
                                                        noconstant=self.get_variable('__noconstant__')
                                                else:
                                                        noconstant=self.add_variable(
                                                                '__noconstant__',1)
                                                        newvars.append(('__noconstant__',1))
                                                newcons['noconstant']=(noconstant>0)
                                                #no variable shift -> same noconstant var as before
                                if constr.typeOfConstraint=='SOcone':
                                        if '__tmplhs[{0}]__'.format(constrKey) in self.variables:
                                                # remove_variable should never called (we let it for security)
                                                self.remove_variable('__tmplhs[{0}]__'.format(constrKey))
                                        if '__tmprhs[{0}]__'.format(constrKey) in self.variables:
                                                self.remove_variable('__tmprhs[{0}]__'.format(constrKey))
                                        tmplhs.append(self.add_variable(
                                                '__tmplhs[{0}]__'.format(constrKey),
                                                constr.Exp1.size))
                                        tmprhs.append(self.add_variable(
                                                '__tmprhs[{0}]__'.format(constrKey),
                                                1))
                                        newvars.append(('__tmplhs[{0}]__'.format(constrKey),
                                                constr.Exp1.size[0]*constr.Exp1.size[1]))
                                        newvars.append(('__tmprhs[{0}]__'.format(constrKey),
                                                1))
                                        #v_cons is 0/1/-1 to avoid constants in cone (problem with duals)
                                        v_cons = cvx.matrix( [np.sign(constr.Exp1.constant[i])
                                                                        if (constr.Exp1.constant is not None) and constr.Exp1[i].isconstant() else 0
                                                                        for i in range(constr.Exp1.size[0]*constr.Exp1.size[1])],
                                                                        constr.Exp1.size)
                                        #lhs and rhs of the cone constraint
                                        newcons['tmp_lhs_{0}'.format(constrKey)]=(
                                                        constr.Exp1+v_cons*noconstant == tmplhs[-1])
                                        newcons['tmp_rhs_{0}'.format(constrKey)]=(
                                                        constr.Exp2-noconstant == tmprhs[-1])
                                        #conic constraints
                                        newcons['tmp_conesign_{0}'.format(constrKey)]=(
                                                        tmprhs[-1]>0)
                                        newcons['tmp_conequad_{0}'.format(constrKey)]=(
                                        -tmprhs[-1]**2+(tmplhs[-1]|tmplhs[-1])<0)
                                        icone+=1
                                if constr.typeOfConstraint=='RScone':
                                        if '__tmplhs[{0}]__'.format(constrKey) in self.variables:
                                                self.remove_variable('__tmplhs[{0}]__'.format(constrKey))
                                        if '__tmprhs[{0}]__'.format(constrKey) in self.variables:
                                                self.remove_variable('__tmprhs[{0}]__'.format(constrKey))
                                        tmplhs.append(self.add_variable(
                                                '__tmplhs[{0}]__'.format(constrKey),
                                                (constr.Exp1.size[0]*constr.Exp1.size[1])+1
                                                ))
                                        tmprhs.append(self.add_variable(
                                                '__tmprhs[{0}]__'.format(constrKey),
                                                1))
                                        newvars.append(('__tmplhs[{0}]__'.format(constrKey),
                                                (constr.Exp1.size[0]*constr.Exp1.size[1])+1))
                                        newvars.append(('__tmprhs[{0}]__'.format(constrKey),
                                                1))
                                        #v_cons is 0/1/-1 to avoid constants in cone (problem with duals)
                                        expcat = ((2*constr.Exp1[:]) // (constr.Exp2-constr.Exp3))
                                        v_cons = cvx.matrix( [np.sign(expcat.constant[i])
                                                                        if (expcat.constant is not None) and expcat[i].isconstant() else 0
                                                                        for i in range(expcat.size[0]*expcat.size[1])],
                                                                        expcat.size)
                                        
                                        #lhs and rhs of the cone constraint
                                        newcons['tmp_lhs_{0}'.format(constrKey)]=(
                                        (2*constr.Exp1[:] // (constr.Exp2-constr.Exp3)) + v_cons*noconstant == tmplhs[-1])
                                        newcons['tmp_rhs_{0}'.format(constrKey)]=(
                                                constr.Exp2+constr.Exp3 - noconstant == tmprhs[-1])
                                        #conic constraints
                                        newcons['tmp_conesign_{0}'.format(constrKey)]=(
                                                        tmprhs[-1]>0)
                                        newcons['tmp_conequad_{0}'.format(constrKey)]=(
                                        -tmprhs[-1]**2+(tmplhs[-1]|tmplhs[-1])<0)
                                        icone+=1
                                
                         
                NUMVAR_NEW = int(_bsum([(var.endIndex-var.startIndex)#new vars including cone vars
                        for var in self.variables.values()
                        if not('cplex' in var.passed)]))
               
                NUMVAR = NUMVAR_OLD + NUMVAR_NEW#total number of variables (including extra vars for cones)
                
                #variables
                
                if (self.options['verbose']>1) and NUMVAR_NEW>0:
                        limitbar=NUMVAR_NEW
                        prog = ProgressBar(0,limitbar, None, mode='fixed')
                        oldprog = str(prog)
                        print('Creating variables...')
                        print
                
                if NUMVAR_NEW:

                        colnames=[]
                        types=[]
                        
                        #specify bounds later, in constraints
                        ub={j:cplex.infinity for j in range(NUMVAR_OLD,NUMVAR)}
                        lb={j:-cplex.infinity for j in range(NUMVAR_OLD,NUMVAR)}
                        
                        
                        for kvar,variable in [(kvar,variable) for (kvar,variable)
                                                in self.variables.iteritems()
                                                if 'cplex' not in variable.passed]:
                                
                                variable.cplex_startIndex=variable.startIndex + OFFSET_CV
                                variable.cplex_endIndex  =variable.endIndex + OFFSET_CV
                                sj=variable.cplex_startIndex
                                ej=variable.cplex_endIndex
                                
                                for ind,(lo,up) in variable.bnd.iteritems():
                                      if not(lo is None):
                                              lb[sj+ind]=lo
                                      if not(up is None):
                                              ub[sj+ind]=up
                                
                        
                        vartopass = sorted([(variable.cplex_startIndex,variable) for (kvar,variable)
                                                in self.variables.iteritems()
                                                if 'cplex' not in variable.passed])
                        
                        for (vcsi,variable) in vartopass:
                                variable.passed.append('cplex')
                                varsize = variable.endIndex-variable.startIndex

                                for k in range(varsize):
                                        colnames.append(variable.name+'_'+str(k))
                                        types.append(cplex_type[variable.vtype])
                                        
                                        if self.options['verbose']>1:
                                                #<--display progress
                                                prog.increment_amount()
                                                if oldprog != str(prog):
                                                        print prog, "\r",
                                                        sys.stdout.flush()
                                                        oldprog=str(prog)
                                                #-->
                        
                        if self.options['verbose']>1:
                                prog.update_amount(limitbar)
                                print prog, "\r",
                                print
                
                
                        
                #parse all vars for hotstart
                mipstart_ind=[]
                mipstart_vals=[]
                if self.options['hotstart']:
                        for kvar,variable in self.variables.iteritems():
                                sj=variable.cplex_startIndex
                                ej=variable.cplex_endIndex
                                if variable.is_valued():
                                        mipstart_ind.extend(range(sj,ej))
                                        mipstart_vals.extend(variable.value)
                                        
                #parse all variable for the obective (only if not obj_passed)
                newobjcoefs=[]
                quad_terms = []
                if 'cplex' not in self.obj_passed:
                        self.obj_passed.append('cplex')
                        
                        if self.objective[1] is None:
                                objective = {}
                        elif isinstance(self.objective[1],QuadExp):
                                objective = self.objective[1].aff.factors
                        elif isinstance(self.objective[1],AffinExp):
                                objective = self.objective[1].factors
                        
                        for variable,vect in objective.iteritems():
                                sj = variable.cplex_startIndex
                                newobjcoefs.extend(zip(vect.J+sj,vect.V))
                    
                    
                        if isinstance(self.objective[1],QuadExp):
                                qd=self.objective[1].quad
                                for i,j in qd:
                                        fact=qd[i,j]
                                        si=i.cplex_startIndex
                                        sj=j.cplex_startIndex
                                        if (j,i) in qd: #quad stores x'*A1*y + y'*A2*x
                                                if si<sj:
                                                        fact+=qd[j,i].T
                                                elif si>sj:
                                                        fact=cvx.sparse([0])
                                                elif si==sj:
                                                        pass
                                        quad_terms += zip(fact.I+si,fact.J+sj,2*fact.V)
                                                       
                #constraints
                
                NUMCON_NEW = int(_bsum([(cs.Exp1.size[0] * cs.Exp1.size[1])
                                        for cs in self.constraints
                                        if (cs.typeOfConstraint.startswith('lin'))
                                        and not('cplex' in cs.passed)] +
                                        [1 for cs in self.constraints
                                        if (cs.typeOfConstraint=='quad')
                                        and not('cplex' in cs.passed)]
                                       )
                                )
                                
                
                #progress bar
                if self.options['verbose']>0:
                        print
                        print('adding constraints...')
                        print 
                if self.options['verbose']>1:
                        limitbar= NUMCON_NEW
                        prog = ProgressBar(0,limitbar, None, mode='fixed')
                        oldprog = str(prog)
                
                rows=[]
                cols=[]
                vals=[]
                rhs=[]
                rownames=[]
                senses= ''
                
                ql=[]
                qq=[]
                qc=[]
                
                if only_update:
                        boundcons=self.cplex_boundcons
                else:
                        boundcons={} #dictionary of i,j,b,v for bound constraints
                
                
                #join all constraints
                def join_iter(it1,it2):
                        for i in it1: yield i
                        for i in it2: yield i
                        
                allcons = join_iter(enumerate(self.constraints),
                                    newcons.iteritems())
                
                irow=0
                for constrKey,constr in allcons:
                        if 'cplex' in constr.passed:
                                continue
                        else:
                                constr.passed.append('cplex')
                       
                        if constr.typeOfConstraint[:3] == 'lin':
                                #init of boundcons[key]
                                boundcons[constrKey]=[]
                                
                                #parse the (i,j,v) triple
                                ijv=[]
                                for var,fact in (constr.Exp1-constr.Exp2).factors.iteritems():
                                        if type(fact)!=cvx.base.spmatrix:
                                                fact = cvx.sparse(fact)
                                        sj=var.cplex_startIndex
                                        ijv.extend(zip( fact.I,fact.J+sj,fact.V))
                                ijvs=sorted(ijv)
                                
                                itojv={}
                                lasti=-1
                                for (i,j,v) in ijvs:
                                        if i==lasti:
                                                itojv[i].append((j,v))
                                        else:
                                                lasti=i
                                                itojv[i]=[(j,v)]
                                
                                #constant term
                                szcons = constr.Exp1.size[0]*constr.Exp1.size[1]
                                rhstmp = cvx.matrix(0.,(szcons,1))
                                constant1 = constr.Exp1.constant #None or a 1*1 matrix
                                constant2 = constr.Exp2.constant
                                if not constant1 is None:
                                        rhstmp = rhstmp-constant1
                                if not constant2 is None:
                                        rhstmp = rhstmp+constant2
                                                
                                for i,jv in itojv.iteritems():
                                        r=rhstmp[i]
                                        if len(jv)==1:
                                                #BOUND
                                                j,v=jv[0]
                                                b=r/float(v)
                                                if j < NUMVAR_OLD:
                                                        clj = c.variables.get_lower_bounds(j)
                                                        cuj = c.variables.get_upper_bounds(j)
                                                else:
                                                        clj = lb[j]
                                                        cuj = ub[j]
                                                if v>0:
                                                        if constr.typeOfConstraint[:4] in ['lin<','lin=']:
                                                                if b<cuj:
                                                                        ub[j]=b
                                                        if constr.typeOfConstraint[:4] in ['lin>','lin=']:
                                                                if b>clj:
                                                                        lb[j]=b
                                                else:#v<0
                                                        if constr.typeOfConstraint[:4] in ['lin<','lin=']:
                                                                if b>clj:
                                                                        lb[j]=b
                                                        if constr.typeOfConstraint[:4] in ['lin>','lin=']:
                                                                if b<cuj:
                                                                        ub[j]=b
                                                if constr.typeOfConstraint[3]=='=': 
                                                        b='='
                                                boundcons[constrKey].append((i,j,b,v))
                                        else:
                                                if constr.typeOfConstraint[:4] == 'lin<':
                                                        senses += "L" # lower
                                                elif constr.typeOfConstraint[:4] == 'lin>':
                                                        senses += "G" # greater
                                                elif constr.typeOfConstraint[:4] == 'lin=':
                                                        senses += "E" # equal
                                                
                                                rows.extend([irow]*len(jv))
                                                cols.extend([j for j,v in jv])
                                                vals.extend([v for j,v in jv])
                                                rhs.append(r)
                                                irow+=1
                                                rownames.append('lin'+str(constrKey)+'_'+str(i))
                                                
                                        if self.options['verbose']>1:
                                                #<--display progress
                                                prog.increment_amount()
                                                if oldprog != str(prog):
                                                        print prog, "\r",
                                                        sys.stdout.flush()
                                                        oldprog=str(prog)
                                                #-->                                                
                        
                        elif constr.typeOfConstraint == 'quad':
                                #quad part
                                qind1,qind2,qval=[],[],[]
                                qd=constr.Exp1.quad
                                for i,j in qd:
                                        fact=qd[i,j]
                                        si=i.cplex_startIndex
                                        sj=j.cplex_startIndex
                                        if (j,i) in qd: #quad stores x'*A1*y + y'*A2*x
                                                if si<sj:
                                                        fact+=qd[j,i].T
                                                elif si>sj:
                                                        fact=cvx.sparse([0])
                                                elif si==sj:
                                                        pass
                                        qind1.extend(fact.I+si)
                                        qind2.extend(fact.J+sj)
                                        qval.extend(fact.V)
                                q_exp=cplex.SparseTriple(ind1 = qind1,
                                                         ind2 = qind2,
                                                         val = qval)
                                #lin part
                                lind,lval=[],[]
                                af=constr.Exp1.aff.factors
                                for var in af:
                                        sj=var.cplex_startIndex
                                        lind.extend(af[var].J + sj)
                                        lval.extend(af[var].V)
                                l_exp=cplex.SparsePair(ind = lind, val = lval)
                                
                                #constant
                                qcs=0.
                                if not(constr.Exp1.aff.constant is None):
                                        qcs = - constr.Exp1.aff.constant[0]
                                
                                ql+= [l_exp]
                                qq+= [q_exp]
                                qc+= [qcs]
                                
                                if self.options['verbose']>1:
                                        #<--display progress
                                        prog.increment_amount()
                                        if oldprog != str(prog):
                                                print prog, "\r",
                                                sys.stdout.flush()
                                                oldprog=str(prog)
                                        #-->
                                
                        elif constr.typeOfConstraint[2:] == 'cone':
                                boundcons[constrKey]=[]
                                #will be handled in the newcons dictionary
                                
                        else:
                                raise Exception('type of constraint not handled (yet ?) for cplex:{0}'.format(
                                        constr.typeOfConstraint))
                                
                      

                if self.options['verbose']>1:
                        prog.update_amount(limitbar)
                        print prog, "\r",
                        print
                
                if self.options['verbose']>0:
                        print
                        print('Passing to cplex...')
                
                
                c.variables.add(names = colnames,types=types)
                c.variables.set_lower_bounds(lb.iteritems())
                c.variables.set_upper_bounds(ub.iteritems())
                c.objective.set_linear(newobjcoefs)
                        
                if len(quad_terms)>0:
                        c.objective.set_quadratic_coefficients(quad_terms)
                
                offset=c.linear_constraints.get_num()
                rows=[r+offset for r in rows]
                c.linear_constraints.add(rhs = rhs, senses = senses,names=rownames)
                
                if len(rows)>0:
                        c.linear_constraints.set_coefficients(zip(rows, cols, vals))
                for lp,qp,qcs in zip(ql,qq,qc):
                        c.quadratic_constraints.add(lin_expr = lp,
                                                    quad_expr = qp,
                                                    rhs = qcs,
                                                    sense = "L")
                
                if self.options['hotstart'] and len(mipstart_ind)>0:
                        c.MIP_starts.add(cplex.SparsePair(
                                        ind=mipstart_ind,val=mipstart_vals),
                                        c.MIP_starts.effort_level.repair)
                
                tp=self.type
                if tp == 'LP':
                        c.set_problem_type(c.problem_type.LP)
                elif tp == 'MIP':
                        c.set_problem_type(c.problem_type.MILP)
                elif tp in ('QCQP','SOCP','Mixed (SOCP+quad)'):
                        c.set_problem_type(c.problem_type.QCP)
                elif tp in ('MIQCP','MISOCP','Mixed (MISOCP+quad)'):
                        c.set_problem_type(c.problem_type.MIQCP)
                elif tp == 'QP':
                        c.set_problem_type(c.problem_type.QP)
                elif tp == 'MIQP':
                        c.set_problem_type(c.problem_type.MIQP)
                else:
                        raise Exception('unhandled type of problem')
                
                
                self.cplex_Instance = c
                self.cplex_boundcons=boundcons
                
                if 'noconstant' in newcons or len(tmplhs)>0:
                        self._remove_temporary_variables()
                
                
                if self.options['verbose']>0:
                        print('CPLEX INSTANCE created')
               

                
        def _make_cvxopt_instance(self,aff_part_of_quad=True,cone_as_quad=False):
                """
                defines the variables in self.cvxoptVars, used by the cvxopt solver
                """
                ss=self.numberOfVars
                #initial values                
                self.cvxoptVars['A']=cvx.spmatrix([],[],[],(0,ss),tc='d')
                self.cvxoptVars['b']=cvx.matrix([],(0,1),tc='d')
                self.cvxoptVars['Gl']=cvx.spmatrix([],[],[],(0,ss),tc='d')
                self.cvxoptVars['hl']=cvx.matrix([],(0,1),tc='d')
                self.cvxoptVars['Gq']=[]
                self.cvxoptVars['hq']=[]
                self.cvxoptVars['Gs']=[]
                self.cvxoptVars['hs']=[]
                self.cvxoptVars['quadcons']=[]
                #objective
                if isinstance(self.objective[1],QuadExp):
                        self.cvxoptVars['quadcons'].append(('_obj',-1))
                        objexp=self.objective[1].aff
                elif isinstance(self.objective[1],LogSumExp):
                        objexp=self.objective[1].Exp
                else:
                        objexp=self.objective[1]
                if self.numberLSEConstraints==0:
                        if self.objective[0]=='find':
                                self.cvxoptVars['c']=cvx.matrix(0,(ss,1),tc='d')
                        elif self.objective[0]=='min':
                                (c,constantInObjective)=self._makeGandh(objexp)
                                self.cvxoptVars['c']=cvx.matrix(c,tc='d').T
                        elif self.objective[0]=='max':
                                (c,constantInObjective)=self._makeGandh(objexp)
                                self.cvxoptVars['c']=-cvx.matrix(c,tc='d').T
                else:
                        if self.objective[0]=='find':
                                self.cvxoptVars['F']=cvx.matrix(0,(1,ss),tc='d')
                                self.cvxoptVars['K']=[0]
                        else:
                                (F,g)=self._makeGandh(objexp)
                                self.cvxoptVars['K']=[F.size[0]]
                                if self.objective[0]=='min':
                                        self.cvxoptVars['F']=cvx.matrix(F,tc='d')
                                        self.cvxoptVars['g']=cvx.matrix(g,tc='d')
                                elif self.objective[0]=='max':
                                        self.cvxoptVars['F']=-cvx.matrix(F,tc='d')
                                        self.cvxoptVars['g']=-cvx.matrix(g,tc='d')
                
                if not(aff_part_of_quad) and isinstance(self.objective[1],QuadExp):
                        self.cvxoptVars['c']=cvx.matrix(0,(ss,1),tc='d')

                if self.options['verbose']>1:
                        limitbar=self.numberAffConstraints + self.numberConeConstraints + self.numberQuadConstraints + self.numberLSEConstraints + self.numberSDPConstraints
                        prog = ProgressBar(0,limitbar, None, mode='fixed')
                        oldprog = str(prog)
                
                #constraints                
                for k in range(len(self.constraints)):
                        #linear constraints                        
                        if self.constraints[k].typeOfConstraint[:3]=='lin':
                                sense=self.constraints[k].typeOfConstraint[3]
                                (G_lhs,h_lhs)=self._makeGandh(self.constraints[k].Exp1)
                                (G_rhs,h_rhs)=self._makeGandh(self.constraints[k].Exp2)
                                if sense=='=':
                                        self.cvxoptVars['A']=cvx.sparse([self.cvxoptVars['A'],G_lhs-G_rhs])
                                        self.cvxoptVars['b']=cvx.matrix([self.cvxoptVars['b'],h_rhs-h_lhs])
                                elif sense=='<':
                                        self.cvxoptVars['Gl']=cvx.sparse([self.cvxoptVars['Gl'],G_lhs-G_rhs])
                                        self.cvxoptVars['hl']=cvx.matrix([self.cvxoptVars['hl'],h_rhs-h_lhs])
                                elif sense=='>':
                                        self.cvxoptVars['Gl']=cvx.sparse([self.cvxoptVars['Gl'],G_rhs-G_lhs])
                                        self.cvxoptVars['hl']=cvx.matrix([self.cvxoptVars['hl'],h_lhs-h_rhs])
                                else:
                                        raise NameError('unexpected case')
                        elif self.constraints[k].typeOfConstraint=='SOcone':
                                if not(cone_as_quad):
                                        (A,b)=self._makeGandh(self.constraints[k].Exp1)
                                        (c,d)=self._makeGandh(self.constraints[k].Exp2)
                                        self.cvxoptVars['Gq'].append(cvx.sparse([-c,-A]))
                                        self.cvxoptVars['hq'].append(cvx.matrix([d,b]))
                                else:
                                        self.cvxoptVars['quadcons'].append(
                                                (k,self.cvxoptVars['Gl'].size[0]))
                                        if aff_part_of_quad:
                                                raise Exception('cone_as_quad + aff_part_of_quad')
                        elif self.constraints[k].typeOfConstraint=='RScone':
                                if not(cone_as_quad):
                                        (A,b)=self._makeGandh(self.constraints[k].Exp1)
                                        (c1,d1)=self._makeGandh(self.constraints[k].Exp2)
                                        (c2,d2)=self._makeGandh(self.constraints[k].Exp3)
                                        self.cvxoptVars['Gq'].append(cvx.sparse([-c1-c2,-2*A,c2-c1]))
                                        self.cvxoptVars['hq'].append(cvx.matrix([d1+d2,2*b,d1-d2]))
                                else:
                                        self.cvxoptVars['quadcons'].append(
                                                (k,self.cvxoptVars['Gl'].size[0]))
                                        if aff_part_of_quad:
                                                raise Exception('cone_as_quad + aff_part_of_quad')
                        elif self.constraints[k].typeOfConstraint=='lse':
                                (F,g)=self._makeGandh(self.constraints[k].Exp1)
                                self.cvxoptVars['F']=cvx.sparse([self.cvxoptVars['F'],F])
                                self.cvxoptVars['g']=cvx.matrix([self.cvxoptVars['g'],g])
                                self.cvxoptVars['K'].append(F.size[0])
                        elif self.constraints[k].typeOfConstraint=='quad':
                                self.cvxoptVars['quadcons'].append((k,self.cvxoptVars['Gl'].size[0]))
                                if aff_part_of_quad:
                                        #quadratic part handled later
                                        (G_lhs,h_lhs)=self._makeGandh(self.constraints[k].Exp1.aff)
                                        self.cvxoptVars['Gl']=cvx.sparse([self.cvxoptVars['Gl'],G_lhs])
                                        self.cvxoptVars['hl']=cvx.matrix([self.cvxoptVars['hl'],-h_lhs])
                        elif self.constraints[k].typeOfConstraint[:3]=='sdp':
                                sense=self.constraints[k].typeOfConstraint[3]
                                (G_lhs,h_lhs)=self._makeGandh(self.constraints[k].Exp1)
                                (G_rhs,h_rhs)=self._makeGandh(self.constraints[k].Exp2)
                                if sense=='<':
                                        self.cvxoptVars['Gs'].append(G_lhs-G_rhs)
                                        self.cvxoptVars['hs'].append(h_rhs-h_lhs)
                                elif sense=='>':
                                        self.cvxoptVars['Gs'].append(G_rhs-G_lhs)
                                        self.cvxoptVars['hs'].append(h_lhs-h_rhs)
                                else:
                                        raise NameError('unexpected case')
                                
                        else:
                                raise NameError('unexpected case')
                        if self.options['verbose']>1:
                                #<--display progress
                                prog.increment_amount()
                                if oldprog != str(prog):
                                        print prog, "\r",
                                        sys.stdout.flush()
                                        oldprog=str(prog)
                                #-->
                        
                #reshape hs matrices as square matrices
                #for m in self.cvxoptVars['hs']:
                #        n=int(np.sqrt(len(m)))
                #        m.size=(n,n)
                   
                if self.options['verbose']>1:
                        prog.update_amount(limitbar)
                        print prog, "\r",
                        sys.stdout.flush()
                        print

        #-----------
        #mosek tool
        #-----------
        
        # Define a stream printer to grab output from MOSEK
        def _streamprinter(self,text):
                sys.stdout.write(text)
                sys.stdout.flush()

        #separate a linear constraint between 'plain' vars and matrix 'bar' variables
        #J and V denote the sparse indices/values of the constraints for the whole (s-)vectorized vector
        def _separate_linear_cons(self,J,V,idx_sdp_vars):
                #sparse values of the constraint for 'plain' variables
                jj=[]
                vv=[]
                #sparse values of the constraint for the next svec bar variable
                js=[]
                vs=[]
                mats=[]
                offset = 0
                from itertools import izip
                if idx_sdp_vars:
                        idxsdpvars = [ti for ti in idx_sdp_vars]
                        nextsdp = idxsdpvars.pop()
                else:
                        return J,V,[]
                for (j,v) in izip(J,V):
                        if j<nextsdp[0]:
                                jj.append(j-offset)
                                vv.append(v)
                        elif j<nextsdp[1]:
                                js.append(j-nextsdp[0])
                                vs.append(v)
                        else:
                                while j>=nextsdp[1]:
                                        mats.append(svecm1(
                                                cvx.spmatrix(vs,js,[0]*len(js),(nextsdp[1]-nextsdp[0],1)),
                                                triu=True).T)
                                        js=[]
                                        vs=[]
                                        offset+=(nextsdp[1]-nextsdp[0])
                                        try:
                                                nextsdp = idxsdpvars.pop()
                                        except IndexError:
                                                nextsdp = (float('inf'),float('inf'))
                                if j<nextsdp[0]:
                                        jj.append(j-offset)
                                        vv.append(v)
                                elif j<nextsdp[1]:
                                        js.append(j-nextsdp[0])
                                        vs.append(v)
                while len(mats)<len(idx_sdp_vars):
                        mats.append(svecm1(
                                cvx.spmatrix(vs,js,[0]*len(js),(nextsdp[1]-nextsdp[0],1)),
                                triu=True).T)
                        js=[]
                        vs=[]
                        nextsdp=(0,1) #doesnt matter, it will be an empt matrix anyway
                return jj,vv,mats
                
                
        def _make_mosek_instance(self):
                """
                defines the variables msk_env and msk_task used by the solver mosek.
                """
                if self.options['verbose']>0:
                        print('build mosek instance')
                from itertools import izip
                #import mosek
                if self.options['solver'] == 'mosek6': #force to use version 6.0 of mosek.
                        try:
                                import mosek as mosek
                                version7 = not(hasattr(mosek,'cputype'))
                                if version7:
                                        raise ImportError("I could''t find mosek 6.0; the package named mosek is the v7.0")
                        except:
                                raise ImportError('mosek library not found')
                else:#try to load mosek7, else use the default mosek package (which can be any version)
                        try:
                                import mosek7 as mosek
                        except ImportError:
                                try:
                                        import mosek as mosek
                                except:
                                        raise ImportError('mosek library not found')

                version7 = not(hasattr(mosek,'cputype')) #True if this is the version 7 of MOSEK
                        
                if self.msk_env and self.msk_task:
                        env = self.msk_env
                        task = self.msk_task
                else:
                        # Make a MOSEK environment
                        env = mosek.Env ()
                        # Attach a printer to the environment
                        if self.options['verbose']>=1:
                                env.set_Stream (mosek.streamtype.log, self._streamprinter)
                        # Create a task
                        task = env.Task(0,0)
                        # Attach a printer to the task
                        if self.options['verbose']>=1:
                                task.set_Stream (mosek.streamtype.log, self._streamprinter)                                
                        
                # Give MOSEK an estimate of the size of the input data.
                # This is done to increase the speed of inputting data.                                
                reset_hbv_True = False
                NUMVAR_OLD = task.getnumvar()
                if self.options['handleBarVars']:
                        NUMVAR0_OLD = int(_bsum([(var.endIndex-var.startIndex)
                                        for var in self.variables.values()
                                        if not(var.semiDef)
                                        and ('mosek' in var.passed)]))
                        NUMVAR_NEW = int(_bsum([(var.endIndex-var.startIndex)
                                        for var in self.variables.values()
                                        if not(var.semiDef)
                                        and not('mosek' in var.passed)]))
                        
                        indices = [(v.startIndex,v.endIndex,v) for v in self.variables.values()]
                        indices = sorted(indices)
                        idxsdpvars=[(si,ei) for (si,ei,v) in indices[::-1] if v.semiDef]
                        indsdpvar = [i for i,cons in
                                 enumerate([cs for cs in self.constraints if cs.typeOfConstraint.startswith('sdp')])
                                 if cons.semidefVar]
                        
                        if not(idxsdpvars):
                                reset_hbv_True = True
                                self.options._set('handleBarVars',False)
                        
                else:
                        NUMVAR0_OLD = int(_bsum([(var.endIndex-var.startIndex)
                                        for var in self.variables.values()
                                        if ('mosek' in var.passed)]))
                        NUMVAR_NEW = int(_bsum([(var.endIndex-var.startIndex)
                                        for var in self.variables.values()
                                        if not('mosek' in var.passed)]))
               
                NUMVAR = NUMVAR_OLD + NUMVAR_NEW#total number of variables (including extra vars for cones, but not the bar vars)
                NUMVAR0 = NUMVAR0_OLD +  NUMVAR_NEW# number of "plain" vars (without "bar" matrix vars and additional vars for so cones)
                                                   
                NUMCON_OLD = task.getnumcon()
                NUMCON_NEW = int(_bsum([(cs.Exp1.size[0] * cs.Exp1.size[1])
                                        for cs in self.constraints
                                        if (cs.typeOfConstraint.startswith('lin'))
                                        and not('mosek' in cs.passed)] +
                                        [1 for cs in self.constraints
                                        if (cs.typeOfConstraint=='quad')
                                        and not('mosek' in cs.passed)]
                                       )
                                 )

                NUMCON = NUMCON_OLD + NUMCON_NEW
                              
                NUMSDP =  self.numberSDPConstraints
                if NUMSDP>0:
                        #indices = [(v.startIndex,v.endIndex-v.startIndex) for v in self.variables.values()]
                        #indices = sorted(indices)
                        #BARVARDIM = [int((8*sz-1)**0.5/2.) for (_,sz) in indices]
                        BARVARDIM_OLD = [cs.Exp1.size[0]
                                        for cs in self.constraints
                                        if cs.typeOfConstraint.startswith('sdp')
                                        and ('mosek' in cs.passed)]
                        BARVARDIM_NEW = [cs.Exp1.size[0]
                                        for cs in self.constraints 
                                        if cs.typeOfConstraint.startswith('sdp')
                                        and not('mosek' in cs.passed)]
                        BARVARDIM = BARVARDIM_OLD + BARVARDIM_NEW
                else:
                        BARVARDIM_OLD = []
                        BARVARDIM_NEW = []
                        BARVARDIM = []
                        
                
                if (NUMSDP and not(version7)) or self.numberLSEConstraints:
                        raise Exception('SDP or GP constraints are not interfaced. For SDP, try mosek 7.0')
                
                
                #-------------#
                #   new vars  #
                #-------------#
                if version7:
                        #Append 'NUMVAR_NEW' variables.
                        # The variables will initially be fixed at zero (x=0).
                        task.appendvars(NUMVAR_NEW)
                        task.appendbarvars(BARVARDIM_NEW)
                else:
                        task.append(mosek.accmode.var,NUMVAR_NEW)
                
                
                #-------------------------------------------------------------#
                # shift the old cone vars to make some place for the new vars #
                #-------------------------------------------------------------#
                
                #shift in the linear constraints
                if NUMVAR_OLD > NUMVAR0_OLD:
                        for j in xrange(NUMVAR0_OLD,NUMVAR_OLD):
                                sj = [0]*NUMCON_OLD
                                vj = [0]*NUMCON_OLD
                                if version7:
                                        nzj=task.getacol(j,sj,vj)
                                        task.putacol(j,sj[:nzj],[0.]*nzj) #remove the old column
                                        task.putacol(j+NUMVAR_NEW,sj[:nzj],vj[:nzj]) #rewrites it, shifted to the right
                                else:
                                        nzj=task.getavec(mosek.accmode.var,j,sj,vj)
                                        task.putavec(mosek.accmode.var,j,sj[:nzj],[0.]*nzj)
                                        task.putavec(mosek.accmode.var,j+NUMVAR_NEW,sj[:nzj],vj[:nzj])
                        
                #shift in the conic constraints
                nc = task.getnumcone()
                if nc:
                        sub = [0] * NUMVAR_OLD
                for icone in range(nc):
                        (ctype,cpar,sz) = task.getcone(icone,sub)
                        shiftsub = [(s+NUMVAR_NEW if s>=NUMVAR0_OLD else s) for s in sub[:sz]]
                        task.putcone (icone,ctype,cpar,shiftsub)
                        
                #WE DO NOT SHIFT QUADSCOEFS, BOUNDS OR OBJCOEFS SINCE THERE MUST NOT BE ANY
                        
                #-------------#
                #   new cons  #
                #-------------#
                if version7:
                        # Append 'NUMCON_NEW' empty constraints.
                        # The constraints will initially have no bounds.
                        task.appendcons(NUMCON_NEW)
                else:
                        task.append(mosek.accmode.con,NUMCON_NEW)
                
                if self.numberQuadNNZ:
                        task.putmaxnumqnz(int(1.5*self.numberQuadNNZ)) #1.5 factor because the mosek doc
                                                                       #claims it might be good to allocate more space than needed
                #--------------#
                # obj and vars #
                #--------------#
                               
                #find integer variables, put 0-1 bounds on binaries
                ints = []
                for k,var in self.variables.iteritems():
                        if var.vtype=='binary':
                                for ind,i in enumerate(range(var.startIndex,var.endIndex)):
                                        ints.append(i)
                                        (clb,cub) = var.bnd.get(ind,(-INFINITY,INFINITY))
                                        lb = max(0.,clb)
                                        ub = min(1.,cub)
                                        var.bnd._set(ind,(lb,ub))
                                        
                        elif self.variables[k].vtype=='integer':
                                for i in xrange(self.variables[k].startIndex,self.variables[k].endIndex):
                                        ints.append(i)
                                        
                        elif self.variables[k].vtype not in ['continuous','symmetric']:
                                raise Exception('vtype not handled (yet) with mosek')
                if self.options['handleBarVars']:
                        ints,_,mats = self._separate_linear_cons(ints,[0.]*len(ints),idxsdpvars)
                        if any([bool(mat) for mat in mats]):
                                raise Exception('semidef vars with integer elements are not supported')
                
                
                #supress all integers
                for j in range(NUMVAR):
                        task.putvartype(j,mosek.variabletype.type_cont)
                
                #specifies integer variables
                for i in ints:
                        task.putvartype(i,mosek.variabletype.type_int)
                
                
                #objective
                newobj = False
                if 'mosek' not in self.obj_passed:
                        newobj = True
                        self.obj_passed.append('mosek')
                        if self.objective[1]:
                                obj = self.objective[1]
                                subI = []
                                subJ = []
                                subV = []
                                if isinstance(obj,QuadExp):
                                        for i,j in obj.quad:
                                                si,ei=i.startIndex,i.endIndex
                                                sj,ej=j.startIndex,j.endIndex
                                                Qij=obj.quad[i,j]
                                                if not isinstance(Qij,cvx.spmatrix):
                                                        Qij=cvx.sparse(Qij)
                                                if si==sj:#put A+A' on the diag
                                                        sI=list((Qij+Qij.T).I+si)
                                                        sJ=list((Qij+Qij.T).J+sj)
                                                        sV=list((Qij+Qij.T).V)
                                                        for u in range(len(sI)-1,-1,-1):
                                                                #remove when j>i
                                                                if sJ[u]>sI[u]:
                                                                        del sI[u]
                                                                        del sJ[u]
                                                                        del sV[u]
                                                elif si>=ej: #add A in the lower triang
                                                        sI=list(Qij.I+si)
                                                        sJ=list(Qij.J+sj)
                                                        sV=list(Qij.V)
                                                else: #add B' in the lower triang
                                                        sI=list((Qij.T).I+sj)
                                                        sJ=list((Qij.T).J+si)
                                                        sV=list((Qij.T).V)
                                                subI.extend(sI)
                                                subJ.extend(sJ)
                                                subV.extend(sV)
                                        obj = obj.aff
                                
                                JV=[]
                                for var in obj.factors:
                                        mat = obj.factors[var]
                                        for j,v in izip(mat.J,mat.V):
                                                JV.append((var.startIndex+j,v))
                                JV = sorted(JV)
                                J=[ji for (ji,_) in JV]
                                V=[vi for (_,vi) in JV]
                                                
                                if self.options['handleBarVars']:
                                        J,V,mats = self._separate_linear_cons(J,V,idxsdpvars)
                                        
                                        for imat,mat in enumerate(mats):
                                                if mat:
                                                        matij = task.appendsparsesymmat(
                                                                mat.size[0],
                                                                mat.I,mat.J,mat.V)
                                                        task.putbarcj(indsdpvar[imat], [matij], [1.0])
                                        if subI:
                                                subI,subV,mat2 = self._separate_linear_cons(subI,subV,idxsdpvars)
                                                subJ,_,mat3 = self._separate_linear_cons(subJ,[0.]*len(subJ),idxsdpvars)
                                                if (any([bool(mat) for mat in mat2]) or
                                                any([bool(mat) for mat in mat3])):
                                                        raise Exception('quads with sdp bar vars are not supported')
                                for j,v in izip(J,V):
                                        task.putcj(j,v)
                                if subI:
                                        task.putqobj(subI,subJ,subV)
                                        
                #store bound on vars (will be added in the instance at the end)
                vbnds = {}
                for varname in self.varNames:
                        var = self.variables[varname]
                        if 'mosek' not in var.passed:
                                var.passed.append('mosek')
                        else:#retrieve current bounds
                                sz = var.endIndex - var.startIndex
                                si = var.startIndex
                                
                                if self.options['handleBarVars']:
                                        if var.semiDef:
                                                continue#this is a bar var so it has no bounds in the mosek instance
                                        si,_,_ = self._separate_linear_cons([si],[0],idxsdpvars)
                                        si = si[0]
                                bk,bl,bu = [0.]*sz,[0.]*sz,[0.]*sz
                                task.getboundslice(mosek.accmode.var,si,si + sz,bk,bl,bu)
                                for ind,(ky,l,u) in enumerate(izip(bk,bl,bu)):
                                        if ky is mosek.boundkey.lo:
                                                vbnds[var.startIndex+ind] = (l,None)
                                        elif ky is mosek.boundkey.up:
                                                vbnds[var.startIndex+ind] = (None,u)
                                        elif ky is mosek.boundkey.fr:
                                                pass
                                        else:#fx or ra
                                                vbnds[var.startIndex+ind] = (l,u)
                                 
                        for ind,(lo,up) in var.bnd.iteritems():
                                (clo,cup) = vbnds.get(var.startIndex+ind,(None,None))
                                if clo is None: clo = -INFINITY
                                if cup is None: cup = INFINITY
                                nlo = max(clo,lo)
                                nup = min(cup,up)
                                if nlo <= -INFINITY: nlo = None
                                if nup >=  INFINITY: nup = None
                                vbnds[var.startIndex+ind] = (nlo,nup)
                
                for j in range(NUMVAR):
                        #make the variables free
                        task.putbound(mosek.accmode.var,j,mosek.boundkey.fr,0.,0.)

                if not(self.is_continuous()) and self.options['hotstart']:
                        # Set status of all variables to unknown
                        task.makesolutionstatusunknown(mosek.soltype.itg);
                        jj = []
                        sv = []
                        for kvar,variable in self.variables.iteritems():
                                if variable.is_valued():
                                        for i,v in enumerate(variable.value):
                                                jj.append(variable.startIndex + i)
                                                sv.append(v)
                                                
                        if self.options['handleBarVars']:
                                jj,sv,mats = self._separate_linear_cons(jj,sv,idxsdpvars)
                                if any([bool(mat) for mat in mats]):
                                        raise Exception('semidef vars hotstart is not supported')
                                
                        for j,v in izip(jj,sv):
                                task.putsolutioni (
                                        mosek.accmode.var,
                                        j,
                                        mosek.soltype.itg,
                                        mosek.stakey.supbas,
                                        v,
                                        0.0, 0.0, 0.0)
                                
                fxdvars = self.msk_fxd
                if fxdvars is None:
                        fxdvars = {}
                iaff = NUMCON_OLD
                icone=NUMVAR
                tridex = {}
                isdp = len(BARVARDIM_OLD)
                scaled_cols = self.msk_scaledcols
                if scaled_cols is None:
                        scaled_cols = {}
                new_scaled_cols = []
                fxdconevars = self.msk_fxdconevars
                if fxdconevars is None:
                        fxdconevars = []
                allconevars = [t[1] for list_tuples in fxdconevars for t in list_tuples]
                allconevars.extend(range(NUMVAR0,NUMVAR))
                
                #-------------#
                # CONSTRAINTS #
                #-------------#
                
                for idcons,cons in enumerate(self.constraints):
                        if 'mosek' in cons.passed:
                                continue
                        else:
                                cons.passed.append('mosek')
                        if cons.typeOfConstraint.startswith('lin'):
                                fxdvars[idcons] = []
                                #parse the (i,j,v) triple
                                ijv=[]
                                for var,fact in (cons.Exp1-cons.Exp2).factors.iteritems():
                                        if type(fact)!=cvx.base.spmatrix:
                                                fact = cvx.sparse(fact)
                                        sj=var.startIndex
                                        ijv.extend(zip( fact.I,fact.J+sj,fact.V))
                                ijvs=sorted(ijv)
                                
                                itojv={}
                                lasti=-1
                                for (i,j,v) in ijvs:
                                        if i==lasti:
                                                itojv[i].append((j,v))
                                        else:
                                                lasti=i
                                                itojv[i]=[(j,v)]
                                
                                #constant term
                                szcons = cons.Exp1.size[0]*cons.Exp1.size[1]
                                rhstmp = cvx.matrix(0.,(szcons,1))
                                constant1 = cons.Exp1.constant #None or a 1*1 matrix
                                constant2 = cons.Exp2.constant
                                if not constant1 is None:
                                        rhstmp = rhstmp-constant1
                                if not constant2 is None:
                                        rhstmp = rhstmp+constant2
                                
                                for i in range(szcons):
                                        jv = itojv.get(i,[])
                                        J=[jvk[0] for jvk in jv]
                                        V=[jvk[1] for jvk in jv]
                                        
                                        is_fixed_var = (len(J)==1)
                                        if is_fixed_var:
                                                j0=J[0]
                                                v0=V[0]
                                        if self.options['handleBarVars']:
                                                J,V,mats = self._separate_linear_cons(J,V,idxsdpvars)
                                        if is_fixed_var and len(J)==0:
                                                is_fixed_var = False #this is a bound constraint on a bar var, handle as normal cons
                                                if (v0>0 and cons.typeOfConstraint=='lin<') or (v0<0 and cons.typeOfConstraint=='lin>'):
                                                        lo = None
                                                        up = rhstmp[i]/v0
                                                else:
                                                        lo = rhstmp[i]/v0
                                                        up = None
                                                if j0 in vbnds:
                                                        #we handle the cons here, so do not add it at the end
                                                        bdj0 = vbnds[j0]
                                                        if (bdj0[0]==lo) and (lo is not None):
                                                                if bdj0[1] is None:
                                                                        del vbnds[j0]
                                                                else:
                                                                        vbnds[j0] = (None,bdj0[1])
                                                        elif (bdj0[1]==up) and (up is not None):
                                                                if bdj0[0] is None:
                                                                        del vbnds[j0]
                                                                else: 
                                                                        vbnds[j0] = (bdj0[0],None)
                                                        
                                        
                                        if is_fixed_var:
                                                bdj0 = vbnds.get(j0,(-INFINITY,INFINITY))
                                                if cons.typeOfConstraint=='lin=':
                                                        fx = rhstmp[i]/v0
                                                        if fx>=bdj0[0] and fx<=bdj0[1]:
                                                                vbnds[j0] = (fx,fx)
                                                        else:
                                                                raise Exception('an equality constraint is not feasible: xx_{0} = {1}'.format(
                                                                                j0,fx))
                                                        
                                                elif (v0>0 and cons.typeOfConstraint=='lin<') or (v0<0 and cons.typeOfConstraint=='lin>'):
                                                        up = rhstmp[i]/v0
                                                        if up<bdj0[1]:
                                                                vbnds[j0] = (bdj0[0],up)
                                                else:
                                                        lo = rhstmp[i]/v0
                                                        if lo>bdj0[0]:
                                                                vbnds[j0] = (lo,bdj0[1])
                                                
                                                if cons.typeOfConstraint=='lin>':
                                                        fxdvars[idcons].append((i,J[0],-V[0])) #and constraint handled as a bound
                                                else:
                                                        fxdvars[idcons].append((i,J[0],V[0]))
                                                NUMCON -= 1
                                                #remove one unnecessary constraint at the end
                                                if version7:
                                                        task.removecons([NUMCON])
                                                else:
                                                        task.remove(mosek.accmode.con,[NUMCON])
                                                
                                                
                                        else:
                                                b=rhstmp[i]
                                                if version7:
                                                        task.putarow(iaff,J,V)
                                                else:
                                                        task.putaijlist([iaff]*len(J),J,V)
                                                if self.options['handleBarVars']:
                                                        for imat,mat in enumerate(mats):
                                                                if mat:
                                                                        matij = task.appendsparsesymmat(
                                                                                mat.size[0],
                                                                                mat.I,mat.J,mat.V)
                                                                        task.putbaraij(iaff,indsdpvar[imat], [matij], [1.0])
                                                                        
                                                if cons.typeOfConstraint[3]=='=':
                                                        task.putbound(mosek.accmode.con,iaff,mosek.boundkey.fx,
                                                                b,b)
                                                elif cons.typeOfConstraint[3]=='<':
                                                        task.putbound(mosek.accmode.con,iaff,mosek.boundkey.up,
                                                                -INFINITY,b)
                                                elif cons.typeOfConstraint[3]=='>':
                                                        task.putbound(mosek.accmode.con,iaff,mosek.boundkey.lo,
                                                                b,INFINITY)
                                                iaff+=1
                                
                                
                                                       
                        #conic constraints:
                        elif cons.typeOfConstraint.endswith('cone'):
                                
                                conexp = (cons.Exp2 // cons.Exp1[:])
                                if cons.Exp3:
                                        conexp = ((cons.Exp3/2.) // conexp)
                                
                                #parse the (i,j,v) triple
                                ijv=[]
                                for var,fact in conexp.factors.iteritems():
                                        if type(fact)!=cvx.base.spmatrix:
                                                fact = cvx.sparse(fact)
                                        sj=var.startIndex
                                        ijv.extend(zip( fact.I,fact.J+sj,fact.V))
                                ijvs=sorted(ijv)
                                
                                itojv={}
                                lasti=-1
                                for (i,j,v) in ijvs:
                                        if i==lasti:
                                                itojv[i].append((j,v))
                                        else:
                                                lasti=i
                                                itojv[i]=[(j,v)]   
                                
                                #add new eq. cons
                                szcons = conexp.size[0] * conexp.size[1]
                                rhstmp = conexp.constant
                                if rhstmp is None:
                                        rhstmp = cvx.matrix(0.,(szcons,1))

                                istart=icone
                                fxd = []
                                conevars = []
                                #for i,jv in itojv.iteritems():#TODO same error done with other solvers ?
                                for i in range(szcons):
                                        jv = itojv.get(i,[])
                                        J=[jvk[0] for jvk in jv]
                                        V=[-jvk[1] for jvk in jv]
                                        h = rhstmp[i]
                                        if self.options['handleBarVars']:
                                                J,V,mats = self._separate_linear_cons(J,V,idxsdpvars)
                                                for imat,mat in enumerate(mats):
                                                        if mat:
                                                                matij = task.appendsparsesymmat(
                                                                        mat.size[0],
                                                                        mat.I,mat.J,mat.V)
                                                                task.putbaraij(iaff,indsdpvar[imat], [matij], [1.0])
                                        else:#for algorithmic simplicity
                                                mats = [0]
                                        #do we add the variable directly in a cone ?
                                        if (self.options['handleConeVars'] and
                                            len(J)==1 and                               #a single var in the expression
                                            J[0] not in allconevars and                 #not in a cone yet
                                            not(any([mat for mat in mats])) and         #no coef on bar vars
                                            h==0 and                                    #no constant term
                                            #(V[0]==-1 or (J[0] not in ints)) #commented (int vars in cone yield a bug with mosek <6.59)   
                                            J[0] not in ints                            #int. variables cannot be scaled
                                            ):
                                                conevars.append(J[0])
                                                allconevars.append(J[0])
                                                fxd.append((i,J[0]))
                                                if V[0]<>-1:
                                                        scaled_cols[J[0]] = -V[0]
                                                        new_scaled_cols.append(J[0])
                                                
                                        else:#or do we need an extra variable equal to this expression ?
                                                J.append(icone)
                                                V.append(1)
                                                if version7:
                                                        task.appendcons(1)
                                                        task.appendvars(1)
                                                else:
                                                        task.append(mosek.accmode.con,1)
                                                        task.append(mosek.accmode.var,1)
                                                NUMCON += 1
                                                NUMVAR += 1
                                                if version7:
                                                        task.putarow(iaff,J,V)
                                                else:
                                                        task.putaijlist([iaff]*len(J),J,V)
                                                task.putbound(mosek.accmode.con,iaff,mosek.boundkey.fx,h,h)
                                                conevars.append(icone)
                                                iaff+=1
                                                icone+=1
                                iend=icone
                                #sk in quadratic cone
                                if cons.Exp3:
                                        task.appendcone(mosek.conetype.rquad, 0.0, conevars)
                                else:
                                        task.appendcone(mosek.conetype.quad, 0.0, conevars)
                                        
                                for j in xrange(istart,iend):#make extra variable free
                                        task.putbound(mosek.accmode.var,j,mosek.boundkey.fr,0.,0.)
                                fxdconevars.append(fxd)
                
                        #SDP constraints:
                        elif cons.typeOfConstraint.startswith('sdp'):
                                if self.options['handleBarVars'] and cons.semidefVar:
                                        isdp +=1
                                        continue
                        
                                szk = BARVARDIM[isdp]
                                if szk not in tridex:
                                        #tridex[szk] contains a list of all tuples of the form
                                        #(E_ij,index(ij)),
                                        #where ij is an index of a element in the lower triangle
                                        #E_ij is the symm matrix s.t. <Eij|X> = X_ij
                                        #and index(ij) is the index of the pair(ij) counted in column major order
                                        tridex[szk]=[]
                                        idx = -1
                                        for j in range(szk):
                                                for i in range(szk):
                                                        idx+=1
                                                        if i>=j: #(in lowtri)
                                                                if i==j:
                                                                        subi=[i]
                                                                        subj=[i]
                                                                        val=[1.]
                                                                else:
                                                                        subi=[i]
                                                                        subj=[j]
                                                                        val=[0.5]
                                                                Eij = task.appendsparsesymmat(
                                                                        BARVARDIM[isdp],
                                                                        subi,subj,val)
                                                                tridex[szk].append((Eij,idx))
                                
                                if cons.typeOfConstraint=='sdp<':
                                        sdexp = (cons.Exp2 - cons.Exp1)
                                else:
                                        sdexp = (cons.Exp1 - cons.Exp2)
                                
                                #parse the (i,j,v) triple
                                ijv=[]
                                for var,fact in sdexp.factors.iteritems():
                                        if type(fact)!=cvx.base.spmatrix:
                                                fact = cvx.sparse(fact)
                                        sj=var.startIndex
                                        ijv.extend(zip( fact.I,fact.J+sj,fact.V))
                                ijvs=sorted(ijv)
                                
                                itojv={}
                                lasti=-1
                                for (i,j,v) in ijvs:
                                        if i==lasti:
                                                itojv[i].append((j,v))
                                        else:
                                                lasti=i
                                                itojv[i]=[(j,v)] 
                                
                                szcons = sdexp.size[0] * sdexp.size[1]
                                rhstmp = sdexp.constant
                                if rhstmp is None:
                                        rhstmp = cvx.matrix(0.,(szcons,1))
                                      
                                szsym = (szk * (szk+1))/2
                                if version7:
                                        task.appendcons(szsym)
                                else:
                                        task.append(mosek.accmode.con,szsym)
                                NUMCON += szsym
                                for (Eij,idx) in tridex[szk]:
                                        J=[jvk[0] for jvk in itojv.get(idx,[])]
                                        V=[-jvk[1] for jvk in itojv.get(idx,[])]
                                        h = rhstmp[idx]
                                        if self.options['handleBarVars']:
                                                J,V,mats = self._separate_linear_cons(J,V,idxsdpvars)
                                                for imat,mat in enumerate(mats):
                                                        if mat:
                                                                matij = task.appendsparsesymmat(
                                                                        mat.size[0],
                                                                        mat.I,mat.J,mat.V)
                                                                task.putbaraij(iaff,indsdpvar[imat], [matij], [1.0])
                                                                
                                        if J:
                                                task.putarow(iaff,J,V)
                                        task.putbaraij(iaff, isdp, [Eij], [1.0])
                                        task.putbound(mosek.accmode.con,iaff,mosek.boundkey.fx,h,h)
                                        iaff+=1
                                isdp+=1
                        #quadratic constraints:
                        elif cons.typeOfConstraint=='quad':
                                subI=[]
                                subJ=[]
                                subV=[]
                                #quad part
                                
                                qexpr=cons.Exp1
                                for i,j in qexpr.quad:
                                        si,ei=i.startIndex,i.endIndex
                                        sj,ej=j.startIndex,j.endIndex
                                        Qij=qexpr.quad[i,j]
                                        if not isinstance(Qij,cvx.spmatrix):
                                                Qij=cvx.sparse(Qij)
                                        if si==sj:#put A+A' on the diag
                                                sI=list((Qij+Qij.T).I+si)
                                                sJ=list((Qij+Qij.T).J+sj)
                                                sV=list((Qij+Qij.T).V)
                                                for u in range(len(sI)-1,-1,-1):
                                                        #remove when j>i
                                                        if sJ[u]>sI[u]:
                                                                del sI[u]
                                                                del sJ[u]
                                                                del sV[u]
                                        elif si>=ej: #add A in the lower triang
                                                sI=list(Qij.I+si)
                                                sJ=list(Qij.J+sj)
                                                sV=list(Qij.V)
                                        else: #add B' in the lower triang
                                                sI=list((Qij.T).I+sj)
                                                sJ=list((Qij.T).J+si)
                                                sV=list((Qij.T).V)
                                        subI.extend(sI)
                                        subJ.extend(sJ)
                                        subV.extend(sV)
                                #aff part
                                J = []
                                V = []
                                for var in qexpr.aff.factors:
                                        mat = qexpr.aff.factors[var]
                                        for j,v in izip(mat.J,mat.V):
                                                V.append(v)
                                                J.append(var.startIndex+j)
                                                        
                                if self.options['handleBarVars']:
                                        J,V,mats = self._separate_linear_cons(J,V,idxsdpvars)
                                        subI,subV,mat2 = self._separate_linear_cons(subI,subV,idxsdpvars)
                                        subJ,_,mat3 = self._separate_linear_cons(subJ,[0.]*len(subJ),idxsdpvars)
                                        
                                        if (any([bool(mat) for mat in mats]) or
                                            any([bool(mat) for mat in mat2]) or
                                            any([bool(mat) for mat in mat3])):
                                                    raise Exception('quads with sdp bar vars are not supported')
                                        
                                rhs = qexpr.aff.constant
                                if rhs is None:
                                        rhs=0.
                                else:
                                        rhs = -rhs[0]
                                
                                if J:
                                        if version7:
                                                task.putarow(iaff,J,V)
                                        else:
                                                task.putaijlist([iaff]*len(J),J,V)
                                task.putqconk(iaff,subI,subJ,subV)
                                task.putbound(mosek.accmode.con,iaff,mosek.boundkey.up,-INFINITY,rhs)
                                iaff +=1
                        else:
                                raise Exception('type of constraint not handled (yet ?) for mosek:{0}'.format(
                                        constr.typeOfConstraint))
                  
                #bounds on vars and bar vars
                bndjj = []
                bndlo = []
                bndup = []
                for jj in sorted(vbnds.keys()):
                        bndjj.append(jj)
                        (lo,up) = vbnds[jj]
                        if lo is None: lo = -INFINITY
                        if up is None: up =  INFINITY
                        bndlo.append(lo)
                        bndup.append(up)
                        
                if self.options['handleBarVars']:
                        _,bndlo,matslo = self._separate_linear_cons(bndjj,bndlo,idxsdpvars)
                        bndjj,bndup,matsup = self._separate_linear_cons(bndjj,bndup,idxsdpvars)
                for j,lo,up in izip(bndjj,bndlo,bndup):
                        if up>=INFINITY:
                                task.putbound(mosek.accmode.var,j,mosek.boundkey.lo,lo,INFINITY)
                        elif lo<=-INFINITY:
                                task.putbound(mosek.accmode.var,j,mosek.boundkey.up,-INFINITY,up)
                        elif up==lo:
                                task.putbound(mosek.accmode.var,j,mosek.boundkey.fx,lo,lo)
                        else:
                                task.putbound(mosek.accmode.var,j,mosek.boundkey.ra,lo,up)

                if self.options['handleBarVars']:
                        #bounds on bar vars by taking the matslo and matsup one by one
                        for imat,(mlo,mup) in enumerate(zip(matslo,matsup)):
                                for (i,j,v) in izip(mlo.I,mlo.J,mlo.V):
                                        if i==j:
                                                matij = task.appendsparsesymmat(
                                                        mlo.size[0],
                                                        [i],[i],[1.])
                                                lo = v
                                                up = mup[i,j]
                                        else:
                                                matij = task.appendsparsesymmat(
                                                        mlo.size[0],
                                                        [i],[j],[0.5])
                                                lo = v * (2**0.5)
                                                up = mup[i,j] * (2**0.5)
                                        task.putbaraij(iaff,indsdpvar[imat], [matij], [1.0])
                                        if lo<=-INFINITY:
                                                task.putbound(mosek.accmode.con,iaff,mosek.boundkey.up,
                                                        -INFINITY,up)
                                        elif up>=INFINITY:
                                                task.putbound(mosek.accmode.con,iaff,mosek.boundkey.lo,
                                                        lo,INFINITY)
                                        else:
                                                task.putbound(mosek.accmode.con,iaff,mosek.boundkey.ra,
                                                        lo,up)
                                        iaff+=1
                
                #scale columns of variables in cones (simple change of variable which avoids adding an extra var)
                for (j,v) in scaled_cols.iteritems():
                        sj = [0]*NUMCON
                        vj = [0]*NUMCON
                        isnewcone = j in new_scaled_cols
                        if version7: #scale all terms if this is a new cone, only the new rows otherwise
                                nzj=task.getacol(j,sj,vj)
                                task.putacol(j,sj[:nzj],[(vji/v if (isnewcone or i>=NUMCON_OLD) else vji) for (i,vji) in zip(sj[:nzj],vj[:nzj])])
                        else:
                                nzj=task.getavec(mosek.accmode.var,j,sj,vj)
                                task.putavec(mosek.accmode.var,j,sj[:nzj],[(vji/v if (isnewcone or i>=NUMCON_OLD) else vji) for (i,vji) in zip(sj[:nzj],vj[:nzj])])
                        
                        if newobj or isnewcone: #scale the objective coef
                                cj = [0.]
                                task.getcslice(j,j+1,cj)
                                task.putcj(j,cj[0]/v)
                        
                                
                
                #objective sense
                if self.objective[0]=='max':
                        task.putobjsense(mosek.objsense.maximize)
                else:
                        task.putobjsense(mosek.objsense.minimize)
                
                self.msk_env=env
                self.msk_task=task
                self.msk_fxd=fxdvars
                self.msk_scaledcols = scaled_cols
                self.msk_fxdconevars = fxdconevars

                if reset_hbv_True:
                        self.options._set('handleBarVars',True)
                
                if self.options['verbose']>0:
                        print('mosek instance built')
                   
        def _make_mosek_instance_old(self):#TOREMOVE
                """
                defines the variables msk_env and msk_task used by the solver mosek.
                """
                if self.options['verbose']>0:
                        print('build mosek instance')
                
                #import mosek
                if self.options['solver'] == 'mosek6': #force to use version 6.0 of mosek.
                        try:
                                import mosek as mosek
                                version7 = not(hasattr(mosek,'cputype'))
                                if version7:
                                        raise ImportError("I could''t find mosek 6.0; the package named mosek is the v7.0")
                        except:
                                raise ImportError('mosek library not found')
                else:#try to load mosek7, else use the default mosek package (which can be any version)
                        try:
                                import mosek7 as mosek
                        except ImportError:
                                try:
                                        import mosek as mosek
                                except:
                                        raise ImportError('mosek library not found')

                version7 = not(hasattr(mosek,'cputype')) #True if this is the version 7 of MOSEK
                        
                #only change the objective coefficients
                if self.options['onlyChangeObjective']:
                        if self.msk_task is None:
                                raise Exception('option is only available when msk_task has been defined before')
                        newobj=self.objective[1]
                        (cobj,constantInObjective)=self._makeGandh(newobj)
                        self.cvxoptVars['c']=cvx.matrix(cobj,tc='d').T
                        
                        for j in range(len(self.cvxoptVars['c'])):
                        # Set the linear term c_j in the objective.
                                self.msk_task.putcj(j,self.cvxoptVars['c'][j])
                        return
                                
                # Make a MOSEK environment
                env = mosek.Env ()
                # Attach a printer to the environment
                if self.options['verbose']>=1:
                        env.set_Stream (mosek.streamtype.log, self._streamprinter)
                # Create a task
                task = env.Task(0,0)
                # Attach a printer to the task
                if self.options['verbose']>=1:
                        task.set_Stream (mosek.streamtype.log, self._streamprinter)                                
                                
                #patch for quadratic problems with a single var
                if self.numberOfVars==1 and self.numberQuadConstraints>0:
                        if '_ptch_' not in self.variables:
                                ptch=self.add_variable('_ptch_',1)
                        else:
                                ptch=self.get_variable('_ptch_')
                        self.add_constraint( ptch>0 )                                
                      
                                
                # Give MOSEK an estimate of the size of the input data.
                # This is done to increase the speed of inputting data.                                
                                
                self._make_cvxopt_instance()
                if self.options['handleBarVars']:
                        NUMVAR = self.numberOfVars - int(_bsum([(Gs.size[0]+(Gs.size[0])**0.5)/2.
                                             for Gs,Xs in zip(self.cvxoptVars['Gs'],self.cvxoptVars['Xs'])
                                             if Xs]))
                        
                        #start and end indices of the sdpvars, reverted so we can use pop()
                        idxsdpvars=[(var.startIndex,var.endIndex) for var in self.semidefVars[::-1]]
                        indsdpvar=[i for i,Xs in enumerate(self.cvxoptVars['Xs']) if Xs]
                else:
                        NUMVAR = self.numberOfVars
                NUMVAR0 = NUMVAR # number of "plain" vars (without "bar" matrix var)
                #NUMCON = #self.numberAffConstraints plus the quad constraints with an affine part
                NUMCON = 0
                if self.cvxoptVars['A'] is not None:
                        NUMCON += self.cvxoptVars['A'].size[0]
                if self.cvxoptVars['Gl'] is not None:
                        NUMCON += self.cvxoptVars['Gl'].size[0]
                NUMCONE = self.numberConeConstraints
                if NUMCONE>0:
                        varscone = int(_bsum([Gk.size[0] for Gk in self.cvxoptVars['Gq']]))
                        NUMVAR+=varscone
                        NUMCON+=varscone
                
                NUMSDP =  self.numberSDPConstraints
                if NUMSDP>0:
                        if self.options['handleBarVars']:
                                varssdp= int(_bsum([(Gs.size[0]+(Gs.size[0])**0.5)/2.
                                             for Gs,Xs in zip(self.cvxoptVars['Gs'],self.cvxoptVars['Xs'])
                                             if not(Xs)]))
                        else:
                                varssdp= int(_bsum([(Gs.size[0]+(Gs.size[0])**0.5)/2.
                                             for Gs in self.cvxoptVars['Gs']]))
                                
                        NUMCON+=varssdp
                        BARVARDIM = [int((Gs.size[0])**0.5) for Gs in self.cvxoptVars['Gs']]
                else:
                        BARVARDIM = []
                        
                NUMANZ= len(self.cvxoptVars['A'].I)+len(self.cvxoptVars['Gl'].I)
                NUMQNZ= self.numberQuadNNZ

                if (bool(self.cvxoptVars['Gs']) and not(version7)) or bool(self.cvxoptVars['F']):
                        raise Exception('SDP or GP constraints are not interfaced. For SDP, try mosek 7.0')
                
                if version7:
                        # Append 'NUMCON' empty constraints.
                        # The constraints will initially have no bounds.
                        task.appendcons(NUMCON)
                        #Append 'NUMVAR' variables.
                        # The variables will initially be fixed at zero (x=0).
                        task.appendvars(NUMVAR)
                        task.appendbarvars(BARVARDIM)
                else:
                        task.append(mosek.accmode.con,NUMCON)
                        task.append(mosek.accmode.var,NUMVAR)

                #specifies the integer variables
                binaries=[]
                for k in self.variables:
                        if self.variables[k].vtype=='binary':
                                for i in xrange(self.variables[k].startIndex,self.variables[k].endIndex):
                                        task.putvartype(i,mosek.variabletype.type_int)
                                        binaries.append(i)
                        elif self.variables[k].vtype=='integer':
                                for i in xrange(self.variables[k].startIndex,self.variables[k].endIndex):
                                        task.putvartype(i,mosek.variabletype.type_int)
                        elif self.variables[k].vtype not in ['continuous','symmetric']:
                                raise Exception('vtype not handled (yet) with mosek')
                
                if self.options['handleBarVars']:
                        for j in range(NUMVAR):
                                #make the variable free
                                task.putbound(mosek.accmode.var,j,mosek.boundkey.fr,0.,0.)
                                task.putcj(j,0.)
                        
                        cc = cvx.sparse(self.cvxoptVars['c'])
                        if self.objective[0]=='max':#max is handled directly by MOSEK,
                                                        #revert to initial value
                                cc = - cc
                        jj,vv=(cc.I,cc.V)
                        J,V,mats = self._separate_linear_cons(jj,vv,idxsdpvars)
                        for j,v in zip(J,V):
                                task.putcj(j,v)
                                
                        for imat,mat in enumerate(mats):
                                if mat:
                                        matij = task.appendsparsesymmat(
                                                mat.size[0],
                                                mat.I,mat.J,mat.V)
                                        task.putbarcj(indsdpvar[imat], [matij], [1.0])
                                        
                else:
                        for j in range(NUMVAR):
                                # Set the linear term c_j in the objective.
                                if j< self.numberOfVars:
                                        if self.objective[0]=='max':         #max is handled directly by MOSEK,
                                                                        #revert to initial value        
                                                task.putcj(j,-self.cvxoptVars['c'][j])
                                        else:
                                                task.putcj(j,self.cvxoptVars['c'][j])
                                
                                #make the variable free
                                task.putbound(mosek.accmode.var,j,mosek.boundkey.fr,0.,0.)
                                

                for i in binaries:
                        #0/1 bound
                        task.putbound(mosek.accmode.var,i,mosek.boundkey.ra,0.,1.)
                        
                if not(self.is_continuous()) and self.options['hotstart']:
                        # Set status of all variables to unknown
                        task.makesolutionstatusunknown(mosek.soltype.itg);
                        for kvar,variable in self.variables.iteritems():
                                if variable.is_valued():
                                        startvar = variable.value
                                        for jk,j in enumerate(range(variable.startIndex,variable.endIndex)):
                                                task.putsolutioni (
                                                  mosek.accmode.var,
                                                  j,
                                                  mosek.soltype.itg,
                                                  mosek.stakey.supbas,
                                                  startvar[jk],
                                                  0.0, 0.0, 0.0)
                                
                fxdvars = []
                bddvars = []
                #equality constraints:
                Ai,Aj,Av=( self.cvxoptVars['A'].I,self.cvxoptVars['A'].J,self.cvxoptVars['A'].V)
                ijvs=sorted(zip(Ai,Aj,Av))
                del Ai,Aj,Av
                itojv={}
                lasti=-1
                for (i,j,v) in ijvs:
                        if i==lasti:
                                itojv[i].append((j,v))
                        else:
                                lasti=i
                                itojv[i]=[(j,v)]
                iaff=0
                for i,jv in itojv.iteritems():
                        J=[jvk[0] for jvk in jv]
                        V=[jvk[1] for jvk in jv]
                        if self.options['handleBarVars']:
                                J,V,mats = self._separate_linear_cons(J,V,idxsdpvars)
                        is_fixed_var = (len(J)==1)
                        if is_fixed_var and self.options['handleBarVars']:
                                if any([bool(mat) for mat in mats]):
                                        is_fixed_var = False
                        
                        
                        if is_fixed_var:
                                #fixed variable
                                fxdvars.append((i,J[0],V[0]))
                                b=self.cvxoptVars['b'][i]/V[0]
                                task.putbound(mosek.accmode.var,J[0],mosek.boundkey.fx,b,b)
                        else:
                        
                                #affine inequality
                                b=self.cvxoptVars['b'][i]
                                task.putaijlist([iaff]*len(J),J,V)
                                if self.options['handleBarVars']:
                                        for imat,mat in enumerate(mats):
                                                if mat:
                                                        matij = task.appendsparsesymmat(
                                                                mat.size[0],
                                                                mat.I,mat.J,mat.V)
                                                        task.putbaraij(iaff,indsdpvar[imat], [matij], [1.0])
                                                        
                                task.putbound(mosek.accmode.con,iaff,mosek.boundkey.fx,
                                                b,b)
                                iaff+=1

                #inequality constraints:
                Gli,Glj,Glv=( self.cvxoptVars['Gl'].I,self.cvxoptVars['Gl'].J,self.cvxoptVars['Gl'].V)
                ijvs=sorted(zip(Gli,Glj,Glv))
                del Gli,Glj,Glv
                itojv={}
                lasti=-1
                for (i,j,v) in ijvs:
                        if i==lasti:
                                itojv[i].append((j,v))
                        else:
                                lasti=i
                                itojv[i]=[(j,v)]
                
                for i,jv in itojv.iteritems():
                        J=[jvk[0] for jvk in jv]
                        V=[jvk[1] for jvk in jv]
                        if self.options['handleBarVars']:
                                J,V,mats = self._separate_linear_cons(J,V,idxsdpvars)
                        is_bounded_var = (len(J)==1 and (not (i in [t[1] for t in self.cvxoptVars['quadcons']])) )
                        if is_bounded_var and self.options['handleBarVars']:
                                if any([bool(mat) for mat in mats]):
                                        is_bounded_var = False
                                
                                
                        if is_bounded_var:
                                #bounded variable
                                bddvars.append((i,J[0],V[0]))
                                bk,bl,bu=task.getbound(mosek.accmode.var,J[0])
                                b=self.cvxoptVars['hl'][i]/V[0]
                                if V[0]>0:
                                        #less than
                                        bu=min(b,bu)
                                if V[0]<0:
                                        #greater than
                                        bl=max(b,bl)
                                if bu==bl:
                                        task.putbound(mosek.accmode.var,J[0],mosek.boundkey.fx,bl,bu)
                                elif bl>bu:
                                        raise Exception('unfeasible bound for var '+str(J[0]))
                                else:
                                        if bl<-INFINITY:
                                                if bu>INFINITY:
                                                        task.putbound(mosek.accmode.var,
                                                        J[0],mosek.boundkey.fr,bl,bu)
                                                else:
                                                        task.putbound(mosek.accmode.var,
                                                        J[0],mosek.boundkey.up,bl,bu)
                                        else:
                                                if bu>INFINITY:
                                                        task.putbound(mosek.accmode.var,
                                                        J[0],mosek.boundkey.lo,bl,bu)
                                                else:
                                                        task.putbound(mosek.accmode.var,
                                                        J[0],mosek.boundkey.ra,bl,bu)
                        else:
                                #affine inequality
                                b=self.cvxoptVars['hl'][i]
                                task.putaijlist([iaff]*len(J),J,V)
                                if self.options['handleBarVars']:
                                        for imat,mat in enumerate(mats):
                                                if mat:
                                                        matij = task.appendsparsesymmat(
                                                                mat.size[0],
                                                                mat.I,mat.J,mat.V)
                                                        task.putbaraij(iaff,indsdpvar[imat], [matij], [1.0])
                                                        
                                task.putbound(mosek.accmode.con,iaff,mosek.boundkey.up,-INFINITY,b)
                                if i in [t[1] for t in self.cvxoptVars['quadcons']]:
                                        #affine part of a quadratic constraint
                                        qcons= [qc for (qc,l) in self.cvxoptVars['quadcons'] if l==i][0]
                                        qconsindex=self.cvxoptVars['quadcons'].index((qcons,i))
                                        self.cvxoptVars['quadcons'][qconsindex]=(qcons,iaff)
                                        #we replace the line number in Gl by the index of the MOSEK constraint
                                iaff+=1
                
                #conic constraints:
                icone=NUMVAR0
                for k in range(NUMCONE):
                        #Gk x + sk = hk
                        istart=icone
                        for i in range(self.cvxoptVars['Gq'][k].size[0]):
                                J=list(self.cvxoptVars['Gq'][k][i,:].J)
                                V=list(self.cvxoptVars['Gq'][k][i,:].V)
                                h=self.cvxoptVars['hq'][k][i]
                                if self.options['handleBarVars']:
                                        J,V,mats = self._separate_linear_cons(J,V,idxsdpvars)
                                        for imat,mat in enumerate(mats):
                                                if mat:
                                                        matij = task.appendsparsesymmat(
                                                                mat.size[0],
                                                                mat.I,mat.J,mat.V)
                                                        task.putbaraij(iaff,indsdpvar[imat], [matij], [1.0])
                                J.append(icone)
                                V.append(1)
                                task.putaijlist([iaff]*len(J),J,V)
                                task.putbound(mosek.accmode.con,iaff,mosek.boundkey.fx,h,h)
                                iaff+=1
                                icone+=1
                        iend=icone
                        #sk in quadratic cone
                        task.appendcone(mosek.conetype.quad, 0.0, range(istart,iend))
                        
                #SDP constraints:
                tridex = {}
                for k in range(NUMSDP):
                        if self.options['handleBarVars'] and k in indsdpvar:
                                continue
                        
                        szk = BARVARDIM[k]
                        if szk not in tridex:
                                #tridex[szk] contains a list of all tuples of the form
                                #(E_ij,index(ij)),
                                #where ij is an index of a element in the lower triangle
                                #E_ij is the symm matrix s.t. <Eij|X> = X_ij
                                #and index(ij) is the index of the pair(ij) counted in column major order
                                tridex[szk]=[]
                                idx = -1
                                for j in range(szk):
                                        for i in range(szk):
                                                idx+=1
                                                if i>=j: #(in lowtri)
                                                        if i==j:
                                                                subi=[i]
                                                                subj=[i]
                                                                val=[1.]
                                                        else:
                                                                subi=[i]
                                                                subj=[j]
                                                                val=[0.5]
                                                        Eij = task.appendsparsesymmat(
                                                                BARVARDIM[k],
                                                                subi,subj,val)
                                                        tridex[szk].append((Eij,idx))
                                                        
                        for (Eij,idx) in tridex[szk]:
                                J = list(self.cvxoptVars['Gs'][k][idx,:].J)
                                V = list(self.cvxoptVars['Gs'][k][idx,:].V)
                                h= self.cvxoptVars['hs'][k][idx]
                                if self.options['handleBarVars']:
                                        J,V,mats = self._separate_linear_cons(J,V,idxsdpvars)
                                        for imat,mat in enumerate(mats):
                                                if mat:
                                                        matij = task.appendsparsesymmat(
                                                                mat.size[0],
                                                                mat.I,mat.J,mat.V)
                                                        task.putbaraij(iaff,indsdpvar[imat], [matij], [1.0])
                                                        
                                task.putarow(iaff,J,V)
                                task.putbaraij(iaff, k, [Eij], [1.0])
                                task.putbound(mosek.accmode.con,iaff,mosek.boundkey.fx,h,h)
                                iaff+=1
                                
                        
                #quadratic constraints:
                task.putmaxnumqnz(NUMQNZ)
                for (k,iaff) in self.cvxoptVars['quadcons']:
                        subI=[]
                        subJ=[]
                        subV=[]
                        if k=='_obj':
                                qexpr=self.objective[1]
                        else:
                                qexpr=self.constraints[k].Exp1

                        for i,j in qexpr.quad:
                                si,ei=i.startIndex,i.endIndex
                                sj,ej=j.startIndex,j.endIndex
                                Qij=qexpr.quad[i,j]
                                if not isinstance(Qij,cvx.spmatrix):
                                        Qij=cvx.sparse(Qij)
                                if si==sj:#put A+A' on the diag
                                        sI=list((Qij+Qij.T).I+si)
                                        sJ=list((Qij+Qij.T).J+sj)
                                        sV=list((Qij+Qij.T).V)
                                        for u in range(len(sI)-1,-1,-1):
                                                #remove when j>i
                                                if sJ[u]>sI[u]:
                                                        del sI[u]
                                                        del sJ[u]
                                                        del sV[u]
                                elif si>=ej: #add A in the lower triang
                                        sI=list(Qij.I+si)
                                        sJ=list(Qij.J+sj)
                                        sV=list(Qij.V)
                                else: #add B' in the lower triang
                                        sI=list((Qij.T).I+sj)
                                        sJ=list((Qij.T).J+si)
                                        sV=list((Qij.T).V)
                                subI.extend(sI)
                                subJ.extend(sJ)
                                subV.extend(sV)
                        
                        if k=='_obj':
                                task.putqobj(subI,subJ,subV)
                        else:
                                task.putqconk(iaff,subI,subJ,subV)
                #objective sense
                if self.objective[0]=='max':
                        task.putobjsense(mosek.objsense.maximize)
                else:
                        task.putobjsense(mosek.objsense.minimize)
                
                self.msk_env=env
                self.msk_task=task
                self.msk_fxd=(fxdvars,bddvars)

                if self.options['verbose']>0:
                        print('mosek instance built')
                        
                        
        def _make_zibopt(self):
                """
                Defines the variables scip_solver, scip_vars and scip_obj,
                used by the zibopt solver.
                """
                try:
                        from zibopt import scip
                except:
                        raise ImportError('scip library not found')
                
                scip_solver = scip.solver(quiet=not(self.options['verbose']))
                
                self._make_cvxopt_instance(aff_part_of_quad=False,cone_as_quad=True)
                
                if bool(self.cvxoptVars['Gs']) or bool(self.cvxoptVars['F']) or bool(self.cvxoptVars['Gq']):
                        raise Exception('SDP, SOCP, or GP constraints are not implemented in zibopt')
                                
                #max handled directly by scip
                if self.objective[0]=='max':
                        self.cvxoptVars['c']=-self.cvxoptVars['c']
                
                zib_types={ 'continuous':scip.CONTINUOUS,
                            'integer'   :scip.INTEGER,
                            'binary'    :scip.BINARY,
                            'symmetric' :scip.CONTINUOUS
                           }
                types=[0]*self.cvxoptVars['A'].size[1]
                for var in self.variables.keys():
                                si=self.variables[var].startIndex
                                ei=self.variables[var].endIndex
                                vtype=self.variables[var].vtype
                                try:
                                        types[si:ei]=[zib_types[vtype]]*(ei-si)
                                except:
                                        raise Exception('this vtype is not handled by scip: '+str(vtype))
                
                x=[]
                INFINITYZO = 1e10
                for i in range(self.cvxoptVars['A'].size[1]):
                    if not(self.cvxoptVars['c'] is None):
                        x.append(scip_solver.variable(types[i],
                                lower=-INFINITYZO,
                                upper=INFINITYZO,
                                coefficient=self.cvxoptVars['c'][i])
                            )
                    else:
                        x.append(scip_solver.variable(types[i],
                                lower=-INFINITYZO,
                                upper=INFINITYZO
                                ))
                
                #equalities
                Ai,Aj,Av=( self.cvxoptVars['A'].I,self.cvxoptVars['A'].J,self.cvxoptVars['A'].V)
                ijvs=sorted(zip(Ai,Aj,Av))
                del Ai,Aj,Av
                itojv={}
                lasti=-1
                for (i,j,v) in ijvs:
                        if i==lasti:
                                itojv[i].append((j,v))
                        else:
                                lasti=i
                                itojv[i]=[(j,v)]
                        
                for i,jv in itojv.iteritems():
                        exp=0
                        for term in jv:
                                exp+= term[1]*x[term[0]]
                        scip_solver += exp == self.cvxoptVars['b'][i]
                        
                #inequalities
                Gli,Glj,Glv=( self.cvxoptVars['Gl'].I,self.cvxoptVars['Gl'].J,self.cvxoptVars['Gl'].V)
                ijvs=sorted(zip(Gli,Glj,Glv))
                del Gli,Glj,Glv
                itojv={}
                lasti=-1
                for (i,j,v) in ijvs:
                        if i==lasti:
                                itojv[i].append((j,v))
                        else:
                                lasti=i
                                itojv[i]=[(j,v)]
                        
                for i,jv in itojv.iteritems():
                        exp=0
                        for term in jv:
                                exp+= term[1]*x[term[0]]
                        scip_solver += exp <= self.cvxoptVars['hl'][i]

                
                ###
                #quadratic constraints (including SOC constraints)
                for (k,iaff) in self.cvxoptVars['quadcons']:
                        subI=[]
                        subJ=[]
                        subV=[]
                        if k=='_obj':
                                x.append(scip_solver.variable(
                                        zib_types['continuous'],
                                        lower=-INFINITYZO,
                                        upper=INFINITYZO
                                        ))
                                qexpr=self.objective[1]
                        else:
                                if self.constraints[k].typeOfConstraint=='quad':
                                        qexpr=self.constraints[k].Exp1
                                if self.constraints[k].typeOfConstraint=='SOcone':
                                        qexpr=(self.constraints[k].Exp1|self.constraints[k].Exp1)-(
                                                self.constraints[k].Exp2*self.constraints[k].Exp2)
                                        (e2x,e2c)=self._makeGandh(self.constraints[k].Exp2)
                                        exp=e2c[0]
                                        for j,v in zip(e2x.J,e2x.V):
                                                exp+=v*x[j]
                                        if e2x:
                                                scip_solver += exp >=0
                                if self.constraints[k].typeOfConstraint=='RScone':
                                        qexpr=(self.constraints[k].Exp1|self.constraints[k].Exp1)-(
                                                self.constraints[k].Exp2*self.constraints[k].Exp3)
                                        (e2x,e2c)=self._makeGandh(self.constraints[k].Exp2)
                                        exp=e2c[0]
                                        for j,v in zip(e2x.J,e2x.V):
                                                exp+=v*x[j]
                                        if e2x:
                                                scip_solver += exp >=0

                        qd=0
                        for i,j in qexpr.quad:
                                si,ei=i.startIndex,i.endIndex
                                sj,ej=j.startIndex,j.endIndex
                                Qij=qexpr.quad[i,j]
                                if not isinstance(Qij,cvx.spmatrix):
                                        Qij=cvx.sparse(Qij)
                                for ii,jj,vv in zip(Qij.I,Qij.J,Qij.V):
                                        qd+=vv*x[ii+si]*x[jj+sj]
                        
                        if not(qexpr.aff is None):
                                for v,fac in qexpr.aff.factors.iteritems():
                                        if not isinstance(fac,cvx.spmatrix):
                                                fac=cvx.sparse(fac)
                                        sv=v.startIndex
                                        for jj,vv in zip(fac.J,fac.V):
                                                qd+=vv*x[jj+sv]
                                if not(qexpr.aff.constant is None):
                                        qd+=qexpr.aff.constant[0]
                        
                        if k=='_obj':
                                if self.objective[0]=='max':
                                        scip_solver += (x[-1]-qd) <= 0
                                else:
                                        scip_solver += (qd-x[-1]) <= 0
                                self.scip_obj = x[-1]
                        else:
                                scip_solver += qd <= 0
                ###
                
                self.scip_solver=scip_solver
                self.scip_vars=x
                
                
                
                

                
        """
        -----------------------------------------------
        --                CALL THE SOLVER            --
        -----------------------------------------------
        """        

        def solve(self, **options):
                """
                Solves the problem.
                
                Once the problem has been solved, the optimal variables
                can be obtained thanks to the property :attr:`value <picos.Expression.value>`
                of the class :class:`Expression<picos.Expression>`.
                The optimal dual variables can be accessed by the property
                :attr:`dual <picos.Constraint.dual>` of the class
                :class:`Constraint<picos.Constraint>`.
                
                :keyword options: A list of options to update before
                                  the call to the solver. In particular, 
                                  the solver can
                                  be specified here,
                                  under the form ``key = value``.
                                  See the list of available options
                                  in the doc of 
                                  :func:`set_all_options_to_default() <picos.Problem.set_all_options_to_default>`
                :returns: A dictionary which contains the objective value of the problem,
                          the time used by the solver, the status of the solver, and an object
                          which depends on the solver and contains information about the solving process.
                
                """
                if options is None: options={}
                self.update_options(**options)
                if self.options['solver'] is None:
                        self.solver_selection()
                        

                #self._eliminate_useless_variables()

                if isinstance(self.objective[1],GeneralFun):
                        return self._sqpsolve(options)
                
                solve_via_dual = self.options['solve_via_dual']
                if solve_via_dual:
                        converted = False
                        raiseexp = False
                        try:
                                dual = self.dualize()
                        except QuadAsSocpError as ex:
                                if self.options['convert_quad_to_socp_if_needed']:
                                        pcop=self.copy()
                                        try:
                                                pcop.convert_quad_to_socp()
                                                converted = True
                                                dual=pcop.dualize()
                                        except NonConvexError as ex:
                                                raiseexp = True
                                else:
                                        raiseexp = True
                        except Exception as ex:
                                raiseexp = True
                        finally:
                                #if nonconvex:
                                        #raise NonConvexError('Problem is nonconvex')
                                #if nosocpquad:
                                        #raise QuadAsSocpError('Try to convert the quadratic constraints as cone constraints '+
                                                #'with the function convert_quad_to_socp().')
                                if raiseexp:
                                        raise(ex)
                                sol = dual.solve()
                                obj = -sol['obj']
                                if 'noprimals' in self.options and self.options['noprimals']:
                                        pass
                                else:
                                        primals = {}
                                        #the primal variables are the duals of the dual (up to a sign)
                                        xx = dual.constraints[-1].dual
                                        if xx is None:
                                                if self.options['verbose']>0:
                                                        raise Exception("\033[1;31m no Primals retrieved from the dual problem \033[0m")
                                        else:
                                                xx = -xx
                                                indices = [(v.startIndex,v.endIndex,v) for v in self.variables.values()]
                                                indices = sorted(indices,reverse=True)
                                                (start,end,var) = indices.pop()
                                                varvect = []
                                                if converted:
                                                        xx = xx[:-1]
                                                for i,x in enumerate(xx):
                                                        if i<end:
                                                                varvect.append(x)
                                                        else:
                                                                if var.vtype=='symmetric':
                                                                        varvect=svecm1(cvx.matrix(varvect))
                                                                primals[var.name]=cvx.matrix(varvect,var.size)
                                                                varvect = [x]
                                                                (start,end,var) = indices.pop()
                                                if var.vtype=='symmetric':
                                                        varvect=svecm1(cvx.matrix(varvect))
                                                primals[var.name]=cvx.matrix(varvect,var.size)
                                
                                if converted:
                                        self.set_option('noduals',True)
                                if 'noduals' in self.options and self.options['noduals']:
                                        pass
                                else:
                                        duals = []
                                        icone =0 #cone index
                                        isdp  =0 #semidef index
                                        if 'mue' in dual.variables:
                                                eqiter = iter(dual.get_valued_variable('mue'))
                                        if 'mul' in dual.variables:
                                                initer = iter(dual.get_valued_variable('mul'))
                                        for cons in self.constraints:
                                                if cons.typeOfConstraint[2:]=='cone':
                                                        z = dual.get_valued_variable('zs[{0}]'.format(icone))
                                                        lb = dual.get_valued_variable('lbda[{0}]'.format(icone))
                                                        duals.append(cvx.matrix([lb,z]))
                                                        icone+=1
                                                elif cons.typeOfConstraint=='lin=':
                                                        szcons = cons.Exp1.size[0] * cons.Exp1.size[1]
                                                        dd = []
                                                        for i in range(szcons):
                                                                dd.append(eqiter.next())
                                                        duals.append(cvx.matrix(dd))
                                                elif cons.typeOfConstraint.startswith('lin'):#lin ineq
                                                        szcons = cons.Exp1.size[0] * cons.Exp1.size[1]
                                                        dd = []
                                                        for i in range(szcons):
                                                                dd.append(initer.next())
                                                        duals.append(cvx.matrix(dd))
                                                elif cons.typeOfConstraint.startswith('sdp'):
                                                        X = dual.get_valued_variable('X[{0}]'.format(isdp))
                                                        duals.append(X)
                                                        isdp+=1
                else:
                        try:
                                #WARNING: Bug with cvxopt-mosek ?
                                if (self.options['solver']=='CVXOPT' #obolete name, use lower case
                                or self.options['solver']=='cvxopt-mosek'
                                or self.options['solver']=='smcp'
                                or self.options['solver']=='cvxopt'):

                                        primals,duals,obj,sol=self._cvxopt_solve()
                                        
                                # For cplex
                                elif (self.options['solver']=='cplex'):
                                        
                                        primals,duals,obj,sol=self._cplex_solve()

                                # for mosek
                                elif (self.options['solver']=='MSK' #obsolete value, use lower case
                                        or self.options['solver']=='mosek'
                                        or self.options['solver']=='mosek7'
                                        or self.options['solver']=='mosek6'):
                                        
                                        primals,duals,obj,sol=self._mosek_solve()

                                # for scip
                                elif (self.options['solver'] in ('zibopt','scip')):
                                        
                                        primals,duals,obj,sol=self._zibopt_solve()

                                #for gurobi
                                elif (self.options['solver']=='gurobi'):
                                        primals,duals,obj,sol=self._gurobi_solve()
                                        
                                else:
                                        raise Exception('unknown solver')
                        except QuadAsSocpError:
                                if self.options['convert_quad_to_socp_if_needed']:
                                        pcop=self.copy()
                                        pcop.convert_quad_to_socp()
                                        sol=pcop.solve()
                                        self.status=sol['status']
                                        for vname,v in self.variables.iteritems():
                                                v.value=pcop.get_variable(vname).value
                                        for i,cs in enumerate(self.constraints):
                                                dui=pcop.constraints[i].dual
                                                if not(dui is None):
                                                        cs.set_dualVar(dui)
                                        return sol
                                else:
                                        raise
                           
                if 'noprimals' in self.options and self.options['noprimals']:
                        pass
                else:
                        for k in primals.keys():
                                if not primals[k] is None:
                                        self.set_var_value(k,primals[k],optimalvar=True)
                                
                if 'noduals' in self.options and self.options['noduals']:
                        pass
                else:
                        for i,d in enumerate(duals):
                                self.constraints[i].set_dualVar(d)
                if obj=='toEval' and not(self.objective[1] is None):
                        obj=self.objective[1].eval()[0]
                sol['obj']=obj
                self.status=sol['status']
                return sol

                
        def _cvxopt_solve(self):
                """
                Solves a problem with the cvxopt solver.
                """
                
                #-----------------------------#
                # Can we solve this problem ? #
                #-----------------------------#
                
                if self.type in ('unknown type','MISDP','MISOCP','MIQCP','MIQP','MIP','Mixed (MISOCP+quad)') and (
                                self.options['solver']=='cvxopt'):
                        raise NotAppropriateSolverError("'cvxopt' cannot solve problems of type {0}".format(self.type))

                elif self.type in ('unknown type','GP','MISDP','MISOCP','MIQCP','MIQP','MIP','Mixed (MISOCP+quad)') and (
                                self.options['solver']=='smcp'):
                        raise NotAppropriateSolverError("'smcp' cannot solve problems of type {0}".format(self.type))                        
                        
                elif self.type in ('Mixed (SDP+quad)','Mixed (SOCP+quad)','QCQP','QP'):
                        raise QuadAsSocpError('Please convert the quadratic constraints as cone constraints '+
                                                'with the function convert_quad_to_socp().')
                #--------------------#
                # makes the instance #
                #--------------------#
                
                if self.options['onlyChangeObjective']:
                        if self.cvxoptVars['c'] is None:
                                raise Exception('option is only available when cvxoptVars has been defined before')
                        newobj=self.objective[1]
                        (cobj,constantInObjective)=self._makeGandh(newobj)
                        self.cvxoptVars['c']=cvx.matrix(cobj,tc='d').T
                else:
                        self._make_cvxopt_instance()
                self.last_updated_constraint=self.countCons
                #--------------------#        
                #  sets the options  #
                #--------------------#
                import cvxopt.solvers
                abstol=self.options['abstol']
                if abstol is None:
                        abstol = self.options['tol']
                reltol=self.options['reltol']
                if reltol is None:
                        reltol = 10* self.options['tol']
                feastol=self.options['feastol']
                if feastol is None:
                        feastol = self.options['tol']
                maxit=self.options['maxit']
                if maxit is None:
                        maxit=999999
                cvx.solvers.options['maxiters']=maxit
                cvx.solvers.options['abstol']=abstol
                cvx.solvers.options['feastol']=feastol
                cvx.solvers.options['reltol']=reltol
                cvx.solvers.options['show_progress']=bool(self.options['verbose']>0)
                try:
                        import smcp.solvers
                        smcp.solvers.options['maxiters']=maxit
                        smcp.solvers.options['abstol']=abstol
                        smcp.solvers.options['feastol']=feastol
                        smcp.solvers.options['reltol']=reltol
                        smcp.solvers.options['show_progress']=bool(self.options['verbose']>0)
                except:
                        #smcp is not available
                        pass
                
                if self.options['solver'].upper()=='CVXOPT':
                        currentsolver=None
                elif self.options['solver']=='cvxopt-mosek':
                        currentsolver='mosek'
                elif self.options['solver']=='smcp':
                        currentsolver='smcp'
                #-------------------------------#
                #  runs the appropriate solver  #
                #-------------------------------#
                import time
                tstart=time.time()
                
                if self.numberLSEConstraints>0:#GP
                        probtype='GP'
                        if self.options['verbose']>0:
                                print '-----------------------------------'
                                print '         cvxopt GP solver'
                                print '-----------------------------------'
                        sol=cvx.solvers.gp(self.cvxoptVars['K'],
                                                self.cvxoptVars['F'],self.cvxoptVars['g'],
                                                self.cvxoptVars['Gl'],self.cvxoptVars['hl'],
                                                self.cvxoptVars['A'],self.cvxoptVars['b'])
                #changes to adapt the problem for the conelp interface:
                elif currentsolver=='mosek':
                        if len(self.cvxoptVars['Gs'])>0:
                                raise Exception('CVXOPT does not handle SDP with MOSEK')                            
                        if len(self.cvxoptVars['Gq'])+len(self.cvxoptVars['Gs']):
                                if self.options['verbose']>0:
                                        print '------------------------------------------'
                                        print '  mosek LP solver interfaced by cvxopt'
                                        print '------------------------------------------'
                                sol=cvx.solvers.lp(self.cvxoptVars['c'],
                                                self.cvxoptVars['Gl'],self.cvxoptVars['hl'],
                                                self.cvxoptVars['A'],self.cvxoptVars['b'],
                                                solver=currentsolver)
                                probtype='LP'
                        else:
                                if self.options['verbose']>0:
                                        print '-------------------------------------------'
                                        print '  mosek SOCP solver interfaced by cvxopt'
                                        print '-------------------------------------------'
                                sol=cvx.solvers.socp(self.cvxoptVars['c'],
                                                        self.cvxoptVars['Gl'],self.cvxoptVars['hl'],
                                                        self.cvxoptVars['Gq'],self.cvxoptVars['hq'],
                                                        self.cvxoptVars['A'],self.cvxoptVars['b'],
                                                        solver=currentsolver)
                                probtype='SOCP'
                else:
                        dims={}
                        dims['s']=[int(np.sqrt(Gsi.size[0])) for Gsi in self.cvxoptVars['Gs']]
                        dims['l']=self.cvxoptVars['Gl'].size[0]
                        dims['q']=[Gqi.size[0] for Gqi in self.cvxoptVars['Gq']]
                        G=self.cvxoptVars['Gl']
                        h=self.cvxoptVars['hl']
                        # handle the equalities as 2 ineq for smcp
                        if currentsolver=='smcp':
                                if self.cvxoptVars['A'].size[0]>0:
                                       G=cvx.sparse([G,self.cvxoptVars['A']]) 
                                       G=cvx.sparse([G,-self.cvxoptVars['A']])
                                       h=cvx.matrix([h,self.cvxoptVars['b']])
                                       h=cvx.matrix([h,-self.cvxoptVars['b']])
                                       dims['l']+=(2*self.cvxoptVars['A'].size[0])

                        for i in range(len(dims['q'])):
                                G=cvx.sparse([G,self.cvxoptVars['Gq'][i]])
                                h=cvx.matrix([h,self.cvxoptVars['hq'][i]])

                                         
                        for i in range(len(dims['s'])):
                                G=cvx.sparse([G,self.cvxoptVars['Gs'][i]])
                                h=cvx.matrix([h,self.cvxoptVars['hs'][i]])

                        #Remove the lines in A and b corresponding to 0==0        
                        JP=list(set(self.cvxoptVars['A'].I))
                        IP=range(len(JP))
                        VP=[1]*len(JP)
                        
                        idx_0eq0 = [i for i in range(self.cvxoptVars['A'].size[0]) if i not in JP]
                        
                        #is there a constraint of the form 0==a(a not 0) ?
                        if any([b for (i,b) in enumerate(self.cvxoptVars['b']) if i not in JP]):
                                raise Exception('infeasible constraint of the form 0=a')
                        P=cvx.spmatrix(VP,IP,JP,(len(IP),self.cvxoptVars['A'].size[0]))
                        self.cvxoptVars['A']=P*self.cvxoptVars['A']
                        self.cvxoptVars['b']=P*self.cvxoptVars['b']
                        
                        tstart = time.time()
                        if currentsolver=='smcp':
                                try:
                                        import smcp
                                except:
                                        raise Exception('library smcp not found')
                                if self.options['smcp_feas']:
                                        sol=smcp.solvers.conelp(self.cvxoptVars['c'],
                                                        G,h,dims,feas=self.options['smcp_feas'])
                                else:
                                        sol=smcp.solvers.conelp(self.cvxoptVars['c'],
                                                        G,h,dims)
                        else:

                                if self.options['verbose']>0:
                                        print '--------------------------'
                                        print '  cvxopt CONELP solver'
                                        print '--------------------------'
                                sol=cvx.solvers.conelp(self.cvxoptVars['c'],
                                                        G,h,dims,
                                                        self.cvxoptVars['A'],
                                                        self.cvxoptVars['b'])
                        probtype='ConeLP'

                tend = time.time()
                
                status=sol['status']
                solv=currentsolver
                if solv is None: solv='cvxopt'
                if self.options['verbose']>0:
                        print solv+' status: '+status
                                
                #----------------------#
                # retrieve the primals #
                #----------------------#
                primals={}
                if 'noprimals' in self.options and self.options['noprimals']:
                        pass
                else:
                        try:
                                
                                for var in self.variables.values():
                                        si=var.startIndex
                                        ei=var.endIndex
                                        varvect=sol['x'][si:ei]
                                        if var.vtype=='symmetric':
                                                varvect=svecm1(varvect) #varvect was the svec
                                                                        #representation of X
                                        
                                        primals[var.name]=cvx.matrix(varvect, var.size)
                        except Exception as ex:
                                primals = {}
                                if self.options['verbose']>0:
                                        print "\033[1;31m*** Primal Solution not found\033[0m"
                                               
                #--------------------#
                # retrieve the duals #
                #--------------------#
                duals=[]
                if 'noduals' in self.options and self.options['noduals']:
                        pass
                else:
                        try:
                                printnodual=False
                                (indy,indzl,indzq,indznl,indzs)=(0,0,0,0,0)
                                if probtype=='LP' or probtype=='ConeLP':
                                        zkey='z'
                                else:
                                        zkey='zl'
                                zqkey='zq'
                                zskey='zs'
                                if probtype=='ConeLP':
                                        indzq=dims['l']
                                        zqkey='z'
                                        zskey='z'
                                        indzs=dims['l']+_bsum(dims['q'])
                                
                                if currentsolver=='smcp':
                                        ieq=self.cvxoptVars['Gl'].size[0]
                                        neq=(dims['l']-ieq)/2
                                        soleq=sol['z'][ieq:ieq+neq]
                                        soleq-=sol['z'][ieq+neq:ieq+2*neq]
                                else:
                                        soleq=sol['y']
                                
                                for k in range(len(self.constraints)):
                                        #Equality
                                        if self.constraints[k].typeOfConstraint=='lin=':
                                                if not (soleq is None):
                                                        consSz=np.product(self.constraints[k].Exp1.size)
                                                        duals.append((P.T*soleq)[indy:indy+consSz])
                                                        indy+=consSz
                                                else:
                                                        printnodual=True
                                                        duals.append(None)
                                        #Inequality
                                        elif self.constraints[k].typeOfConstraint[:3]=='lin':
                                                if not (sol[zkey] is None):
                                                        consSz=np.product(self.constraints[k].Exp1.size)
                                                        duals.append(sol[zkey][indzl:indzl+consSz])
                                                        indzl+=consSz
                                                else:
                                                        printnodual=True
                                                        duals.append(None)
                                        #SOCP constraint [Rotated or not]
                                        elif self.constraints[k].typeOfConstraint[2:]=='cone':
                                                if not (sol[zqkey] is None):
                                                        if probtype=='ConeLP':
                                                                consSz=np.product(self.constraints[k].Exp1.size)+1
                                                                if self.constraints[k].typeOfConstraint[:2]=='RS':
                                                                        consSz+=1
                                                                duals.append(sol[zqkey][indzq:indzq+consSz])
                                                                duals[-1][1:]=-duals[-1][1:]
                                                                indzq+=consSz
                                                        else:
                                                                duals.append(sol[zqkey][indzq])
                                                                duals[-1][1:]=-duals[-1][1:]
                                                                indzq+=1
                                                else:
                                                        printnodual=True
                                                        duals.append(None)
                                        #SDP constraint
                                        elif self.constraints[k].typeOfConstraint[:3]=='sdp':
                                                if not (sol[zskey] is None):
                                                        if probtype=='ConeLP':
                                                                matsz=self.constraints[k].Exp1.size[0]
                                                                consSz=matsz*matsz
                                                                duals.append(cvx.matrix(sol[zskey][indzs:indzs+consSz],(matsz,matsz)))
                                                                indzs+=consSz
                                                        else:
                                                                matsz=self.constraints[k].Exp1.size[0]
                                                                duals.append(cvx.matrix(sol[zskey][indzs],(matsz,matsz)))
                                                                indzs+=1
                                                else:
                                                        printnodual=True
                                                        duals.append(None)
                                        #GP constraint
                                        elif self.constraints[k].typeOfConstraint=='lse':
                                                if not (sol['znl'] is None):
                                                        consSz=np.product(self.constraints[k].Exp1.size)
                                                        duals.append(sol['znl'][indznl:indznl+consSz])
                                                        indznl+=consSz
                                                else:
                                                        printnodual=True
                                                        duals.append(None)
                                        else:
                                                raise Exception('constraint cannot be handled')
                                        
                                if printnodual and self.options['verbose']>0:
                                        print "\033[1;31m*** Dual Solution not found\033[0m"
                                
                        
                        except Exception as ex:
                                duals = []
                                if self.options['verbose']>0:
                                        print "\033[1;31m*** Dual Solution not found\033[0m"
                
                #-----------------#
                # objective value #
                #-----------------#
                if self.numberLSEConstraints>0:#GP
                        obj='toEval'
                else:#LP or SOCP
                        if sol['primal objective'] is None:
                                if sol['dual objective'] is None:
                                        obj=None
                                else:
                                        obj=sol['dual objective']
                        else:
                                if sol['dual objective'] is None:
                                        obj=sol['primal objective']
                                else:
                                        obj=0.5*(sol['primal objective']+sol['dual objective'])
                        
                        if self.objective[0]=='max' and not obj is None:
                                obj = -obj
                
                solt={'cvxopt_sol':sol,'status':status, 'time':tend-tstart}
                return (primals,duals,obj,solt)
 
        
        def  _cplex_solve(self):
                """
                Solves a problem with the cvxopt solver.
                """

                #-------------------------------#
                #  can we solve it with cplex ? #
                #-------------------------------#
                
                if self.type in ('unknown type','MISDP','GP','SDP','ConeP','Mixed (SDP+quad)'):
                        raise NotAppropriateSolverError("'cplex' cannot solve problems of type {0}".format(self.type))
                
                
                #----------------------------#
                #  create the cplex instance #
                #----------------------------#
                import cplex
                self._make_cplex_instance()
                self.last_updated_constraint=self.countCons
                c = self.cplex_Instance
                
                if c is None:
                        raise ValueError('a cplex instance should have been created before')
                
                
                if not self.options['timelimit'] is None:
                        import cplex_callbacks
                        import time
                        timelim_cb = c.register_callback(cplex_callbacks.TimeLimitCallback)
                        timelim_cb.starttime = time.time()
                        timelim_cb.timelimit = self.options['timelimit']
                        if not self.options['acceptable_gap_at_timelimit'] is None:
                                timelim_cb.acceptablegap =100*self.options['acceptable_gap_at_timelimit']
                        else:
                                timelim_cb.acceptablegap = None
                        timelim_cb.aborted = 0
                        #c.parameters.tuning.timelimit.set(self.options['timelimit']) #DOES NOT WORK LIKE THIS ?
                if not self.options['treememory'] is None:
                        c.parameters.mip.limits.treememory.set(self.options['treememory'])
                if not self.options['gaplim'] is None:
                        c.parameters.mip.tolerances.mipgap.set(self.options['gaplim'])
                #pool of solutions
                if not self.options['pool_size'] is None:
                        c.parameters.mip.limits.solutions.set(self.options['pool_size'])
                if not self.options['pool_gap'] is None:
                        c.parameters.mip.pool.relgap.set(self.options['pool_gap'])
                #verbosity
                c.parameters.barrier.display.set(min(2,self.options['verbose']))
                c.parameters.simplex.display.set(min(2,self.options['verbose']))
                if self.options['verbose']==0:
                        c.parameters.mip.display.set(0)
                     
                #convergence tolerance
                c.parameters.barrier.qcpconvergetol.set(self.options['tol'])
                c.parameters.barrier.convergetol.set(self.options['tol'])
                
                #iterations limit
                if not(self.options['maxit'] is None):
                        
                        c.parameters.barrier.limits.iteration.set(self.options['maxit'])
                        c.parameters.simplex.limits.iterations.set(self.options['maxit'])
                
                #lpmethod
                if not self.options['lp_root_method'] is None:
                        if self.options['lp_root_method']=='psimplex':
                                c.parameters.lpmethod.set(1)
                        elif self.options['lp_root_method']=='dsimplex':
                                c.parameters.lpmethod.set(2)
                        elif self.options['lp_root_method']=='interior':
                                c.parameters.lpmethod.set(4)
                        else:
                                raise Exception('unexpected value for lp_root_method')
                if not self.options['lp_node_method'] is None:
                        if self.options['lp_node_method']=='psimplex':
                                c.parameters.mip.strategy.subalgorithm.set(1)
                        elif self.options['lp_node_method']=='dsimplex':
                                c.parameters.mip.strategy.subalgorithm.set(2)
                        elif self.options['lp_node_method']=='interior':
                                c.parameters.mip.strategy.subalgorithm.set(4)
                        else:
                                raise Exception('unexpected value for lp_node_method')

                if not self.options['nbsol'] is None:
                        c.parameters.mip.limits.solutions.set(self.options['nbsol'])
                        #variant with a call back (count the incumbents)
                        #import cplex_callbacks
                        #nbsol_cb = c.register_callback(cplex_callbacks.nbIncCallback)
                        #nbsol_cb.aborted = 0
                        #nbsol_cb.cursol = 0
                        #nbsol_cb.nbsol = self.options['nbsol']
                
                
                if not self.options['uboundlimit'] is None:
                        import cplex_callbacks
                        bound_cb =  c.register_callback(cplex_callbacks.uboundCallback)
                        bound_cb.aborted = 0
                        bound_cb.ub = INFINITY
                        bound_cb.bound = self.options['uboundlimit']
                   
                if not self.options['lboundlimit'] is None:
                        import cplex_callbacks
                        bound_cb =  c.register_callback(cplex_callbacks.lboundCallback)
                        bound_cb.aborted = 0
                        bound_cb.ub = -INFINITY
                        bound_cb.bound = self.options['lboundlimit']  
                   
                if self.options['boundMonitor']:
                        import cplex_callbacks
                        import time
                        monitor_cb = c.register_callback(cplex_callbacks.boundMonitorCallback)
                        monitor_cb.starttime = time.time()
                        monitor_cb.bounds = []
                        
                   
                #other cplex parameters
                for par,val in self.options['cplex_params'].iteritems():
                        try:
                                cplexpar=eval('c.parameters.'+par)
                                cplexpar.set(val)
                        except AttributeError:
                                raise Exception('unknown cplex param')
                        
                #--------------------#
                #  call the solver   #
                #--------------------#                
                import time
                tstart = time.time()
                
                if not self.options['pool_size'] is None:
                        try:
                                c.populate_solution_pool()
                        except:
                                print "Exception raised during populate"
                else:
                        try:
                                c.solve()
                        except cplex.exceptions.CplexSolverError as ex:
                                if ex.args[2] == 5002:
                                        raise NonConvexError('Error raised during solve. Problem is nonconvex')
                                else:
                                        print "Exception raised during solve"
                tend = time.time()                
        
                self.cplex_Instance = c
                
                # solution.get_status() returns an integer code
                if self.options['verbose']>0:
                        print "Solution status = " +str(c.solution.get_status())+":"
                        # the following line prints the corresponding string
                        print(c.solution.status[c.solution.get_status()])
                status = c.solution.status[c.solution.get_status()]
                
                #----------------------#
                # retrieve the primals #
                #----------------------#
                primals = {}
                obj = c.solution.get_objective_value()
                if 'noprimals' in self.options and self.options['noprimals']:
                        pass
                else:
                        #primals
                        try:
                                numsol = c.solution.pool.get_num()
                                if numsol>1:
                                        objvals=[]
                                        for i in range(numsol):
                                                objvals.append((c.solution.pool.get_objective_value(i),i))
                                        indsols=[]
                                        rev=(self.objective[0]=='max')
                                        for ob,ind in sorted(objvals,reverse=rev)[:self.options['pool_size']]:
                                                indsols.append(ind)
                                
                                for var in self.variables.values():
                                        value = []
                                        sz_var = var.endIndex-var.startIndex
                                        for i in range(sz_var):
                                                name = var.name + '_' + str(i)
                                                value.append(c.solution.get_values(name))
                                        
                                        if var.vtype=='symmetric':
                                                value=svecm1(cvx.matrix(value)) #varvect was the svec
                                                                                #representation of X
                                        primals[var.name] = cvx.matrix(value,var.size)
                                
                                if numsol>1:
                                        for ii,ind in enumerate(indsols):
                                                for var in self.variables.values():
                                                        value = []
                                                        sz_var = var.endIndex-var.startIndex
                                                        for i in range(sz_var):
                                                                name = var.name + '_' + str(i)
                                                                value.append(c.solution.pool.get_values(ind,name))
                                                        if var.vtype=='symmetric':
                                                                value=svecm1(cvx.matrix(value)) #varvect was the svec
                                                                                                #representation of X
                                                        primals[(ii,var.name)] = cvx.matrix(value,var.size)
                        except Exception as ex:
                                import warnings
                                warnings.warn('error while retrieving primals')
                                primals = {}
                                obj = None
                                if self.options['verbose']>0:
                                        print "\033[1;31m*** Primal Solution not found\033[0m"

                        
                #--------------------#
                # retrieve the duals #
                #--------------------#
                
                duals = [] 
                if not(self.isContinuous()) or (
                     'noduals' in self.options and self.options['noduals']):
                        pass
                else:
                        try:
                                version = [int(v) for v in c.get_version().split('.')]
                                #older versions
                                if (version[0]<12) or (version[0]==12 and version[1]<4):
                                        pos_cplex = 0 #row position in the cplex linear constraints
                                        #basis_status = c.solution.basis.get_col_basis()
                                        #>0 and <0
                                        pos_conevar = self.numberOfVars+1 #plus 1 for the __noconstant__ variable 
                                        seen_bounded_vars = []
                                        for k,constr in enumerate(self.constraints):                                               
                                                if constr.typeOfConstraint[:3] == 'lin':
                                                        dim = constr.Exp1.size[0] * constr.Exp1.size[1]
                                                        dim = dim - len(self.cplex_boundcons[k])
                                                        dual_lines = range(pos_cplex, pos_cplex + dim)
                                                        if len(dual_lines)==0:
                                                                dual_values = []
                                                        else:
                                                                dual_values = c.solution.get_dual_values(dual_lines)
                                                        if constr.typeOfConstraint[3]=='>':
                                                                dual_values=[-dvl for dvl in dual_values]
                                                        for (i,j,b,v) in self.cplex_boundcons[k]:
                                                                xj = c.solution.get_values(j)
                                                                if ((b=='=') or abs(xj-b)<1e-7) and (j not in seen_bounded_vars):
                                                                        #does j appear in another equality constraint ?
                                                                        if b!='=':
                                                                                boundsj=[b0 for k0 in range(len(self.constraints))
                                                                                        for (i0,j0,b0,v0) in self.cplex_boundcons[k0]
                                                                                        if j0==j]
                                                                                if '=' in boundsj:
                                                                                        dual_values.insert(i,0.) #dual will be set later, only for the equality case
                                                                                        continue
                                                                        else: #equality
                                                                                seen_bounded_vars.append(j)
                                                                                du=c.solution.get_reduced_costs(j)/v
                                                                                dual_values.insert(i,du)
                                                                                continue
                                                                        #what kind of inequality ?
                                                                        du=c.solution.get_reduced_costs(j)
                                                                        if (((v>0 and constr.typeOfConstraint[3]=='<') or
                                                                        (v<0 and constr.typeOfConstraint[3]=='>')) and
                                                                        du>0):#upper bound
                                                                                seen_bounded_vars.append(j)
                                                                                dual_values.insert(i,du/abs(v))
                                                                        elif (((v>0 and constr.typeOfConstraint[3]=='>') or
                                                                        (v<0 and constr.typeOfConstraint[3]=='<')) and
                                                                        du<0):#lower bound
                                                                                seen_bounded_vars.append(j)
                                                                                dual_values.insert(i,-du/abs(v))
                                                                        else:
                                                                                dual_values.insert(i,0.) #unactive constraint
                                                                else:
                                                                        dual_values.insert(i,0.)
                                                        pos_cplex += dim
                                                        duals.append(cvx.matrix(dual_values))
                                                        
                                                elif constr.typeOfConstraint == 'SOcone':
                                                        szcons = constr.Exp1.size[0]*constr.Exp1.size[1]
                                                        dual_cols = range(pos_conevar,pos_conevar+szcons+1)
                                                        dual_values = c.solution.get_reduced_costs(dual_cols)
                                                        #duals.append(int(np.sign(dual_values[-1])) * cvx.matrix(
                                                                # [dual_values[-1]]+dual_values[:-1]))
                                                        duals.append(cvx.matrix(
                                                                        [-dual_values[-1]]+dual_values[:-1]))
                                                        pos_conevar += szcons+1
                                                
                                                elif constr.typeOfConstraint == 'RScone':
                                                        szcons = constr.Exp1.size[0]*constr.Exp1.size[1]
                                                        dual_cols = range(pos_conevar,pos_conevar+szcons+2)
                                                        dual_values = c.solution.get_reduced_costs(dual_cols)
                                                        #duals.append(int(np.sign(dual_values[-1])) * cvx.matrix(
                                                        #                [dual_values[-1]]+dual_values[:-1]))
                                                        duals.append(cvx.matrix(
                                                                        [-dual_values[-1]]+dual_values[:-1]))
                                                        pos_conevar += szcons+2
                                                
                                                else:
                                                        if self.options['verbose']>0:
                                                                print 'duals for this type of constraint not supported yet'
                                                        duals.append(None)
                                #version >= 12.4
                                else:
                                        seen_bounded_vars = []
                                        for k,constr in enumerate(self.constraints):
                                                if constr.typeOfConstraint[:3] == 'lin':
                                                        dim = constr.Exp1.size[0] * constr.Exp1.size[1]
                                                        dual_values=[None] * dim
                                                        #rows with var bounds
                                                        for (i,j,b,v) in self.cplex_boundcons[k]:
                                                                xj = c.solution.get_values(j)
                                                                if ((b=='=') or abs(xj-b)<1e-4) and (j not in seen_bounded_vars):
                                                                        #does j appear in another equality constraint ?
                                                                        if b!='=':
                                                                                boundsj=[b0 for k0 in range(len(self.constraints))
                                                                                        for (i0,j0,b0,v0) in self.cplex_boundcons[k0]
                                                                                        if j0==j]
                                                                                if '=' in boundsj:
                                                                                        dual_values[i] = 0. #dual will be set later, only for the equality case
                                                                                        continue
                                                                        else: #equality
                                                                                seen_bounded_vars.append(j)
                                                                                du=c.solution.get_reduced_costs(j)/v
                                                                                if self.objective[0]=='min': du=-du
                                                                                dual_values[i] = du
                                                                                continue
                                                                        #what kind of inequality ?
                                                                        du=c.solution.get_reduced_costs(j)
                                                                        if self.objective[0]=='min': du=-du
                                                                        if (((v>0 and constr.typeOfConstraint[3]=='<') or
                                                                        (v<0 and constr.typeOfConstraint[3]=='>')) and
                                                                        du>0):#upper bound
                                                                                seen_bounded_vars.append(j)
                                                                                dual_values[i] = du/abs(v)
                                                                        elif (((v>0 and constr.typeOfConstraint[3]=='>') or
                                                                        (v<0 and constr.typeOfConstraint[3]=='<')) and
                                                                        du<0):#lower bound
                                                                                seen_bounded_vars.append(j)
                                                                                dual_values[i] = -du/abs(v)
                                                                        else:
                                                                                dual_values[i] = 0. #unactive constraint
                                                                else:
                                                                        dual_values[i] = 0.
                                                        
                                                        #rows with other constraints
                                                        for i in range(len(dual_values)):
                                                                if dual_values[i] is None:
                                                                        du = c.solution.get_dual_values(
                                                                                'lin'+str(k)+'_'+str(i))
                                                                        if self.objective[0]=='min': du=-du
                                                                        if constr.typeOfConstraint[3]=='>':
                                                                                dual_values[i] = -du
                                                                        else:
                                                                                dual_values[i] = du
                                                        #import pdb;pdb.set_trace()
                                                        duals.append(cvx.matrix(dual_values))
                                                        
                                                elif constr.typeOfConstraint == 'SOcone':
                                                        dual_values=[]
                                                        dual_values.append(
                                                         c.solution.get_dual_values('lintmp_rhs_'+str(k)+'_0'))
                                                        dim = constr.Exp1.size[0] * constr.Exp1.size[1]
                                                        for i in range(dim):
                                                               dual_values.append(
                                                            -c.solution.get_dual_values('lintmp_lhs_'+str(k)+'_'+str(i)))
                                                        if self.objective[0]=='min':
                                                                duals.append(-cvx.matrix(dual_values))
                                                        else:
                                                                duals.append(cvx.matrix(dual_values))
                                                
                                                elif constr.typeOfConstraint == 'RScone':
                                                        dual_values=[]
                                                        dual_values.append(
                                                        c.solution.get_dual_values('lintmp_rhs_'+str(k)+'_0'))
                                                        dim = 1 + constr.Exp1.size[0] * constr.Exp1.size[1]
                                                        for i in range(dim):
                                                               dual_values.append(
                                                            -c.solution.get_dual_values('lintmp_lhs_'+str(k)+'_'+str(i)))
                                                        if self.objective[0]=='min':
                                                                duals.append(-cvx.matrix(dual_values))
                                                        else:
                                                                duals.append(cvx.matrix(dual_values))
                                                
                                                else:
                                                        if self.options['verbose']>0:
                                                                print 'duals for this type of constraint not supported yet'
                                                        duals.append(None)
                                                        
                                                        
                        except Exception as ex:
                                if self.options['verbose']>0:
                                        print "\033[1;31m*** Dual Solution not found\033[0m"
                #-----------------#
                # return statement#
                #-----------------#             
                
                sol = {'cplex_solution':c.solution,'status':status,'time':(tend - tstart)}
                if self.options['boundMonitor']:
                        sol['bounds_monitor'] = monitor_cb.bounds
                return (primals,duals,obj,sol)
                
        def  _gurobi_solve(self):
                """
                Solves a problem with the cvxopt solver.
                """

                #--------------------------------#
                #  can we solve it with gurobi ? #
                #--------------------------------#
                
                if self.type in ('unknown type','MISDP','GP','SDP','ConeP','Mixed (SDP+quad)'):
                        raise NotAppropriateSolverError("'gurobi' cannot solve problems of type {0}".format(self.type))
                                
                #----------------------------#
                #  create the gurobi instance #
                #----------------------------#
                import gurobipy as grb
                self._make_gurobi_instance()
                self.last_updated_constraint=self.countCons
                m = self.gurobi_Instance
                
                if m is None:
                        raise ValueError('a gurobi instance should have been created before')
                
                
                if not self.options['timelimit'] is None:
                        m.setParam('TimeLimit',self.options['timelimit'])
                if not self.options['treememory'] is None:
                        if self.options['verbose']:
                                print 'option treememory ignored with gurobi'
                        #m.setParam('NodefileStart',self.options['treememory']/1024.)
                        # -> NO In fact this is a limit after which node files are written to disk
                if not self.options['gaplim'] is None:
                        m.setParam('MIPGap',self.options['gaplim'])
                        #m.setParam('MIPGapAbs',self.options['gaplim'])

                #verbosity
                if self.options['verbose']==0:
                        m.setParam('OutputFlag',0)
                       
                #convergence tolerance
                m.setParam('BarQCPConvTol',self.options['tol'])
                m.setParam('BarConvTol',self.options['tol'])
                m.setParam('OptimalityTol',self.options['tol'])
                
                #iterations limit
                if not(self.options['maxit'] is None):
                        m.setParam('BarIterLimit',self.options['maxit'])
                        m.setParam('IterationLimit',self.options['maxit'])
                #lpmethod
                if not self.options['lp_root_method'] is None:
                        if self.options['lp_root_method']=='psimplex':
                                m.setParam('Method',0)
                        elif self.options['lp_root_method']=='dsimplex':
                                m.setParam('Method',1)
                        elif self.options['lp_root_method']=='interior':
                                m.setParam('Method',2)
                        else:
                                raise Exception('unexpected value for lp_root_method')
                if not self.options['lp_node_method'] is None:
                        if self.options['lp_node_method']=='psimplex':
                                m.setParam('SiftMethod',0)
                        elif self.options['lp_node_method']=='dsimplex':
                                m.setParam('SiftMethod',1)
                        elif self.options['lp_node_method']=='interior':
                                m.setParam('SiftMethod',2)
                        else:
                                raise Exception('unexpected value for lp_node_method')

                #number of feasible solutions found
                if not self.options['nbsol'] is None:
                        m.setParam('SolutionLimit',self.options['nbsol'])
                
                
                #other gurobi parameters
                for par,val in self.options['gurobi_params'].iteritems():
                        m.setParam(par,val)
                        
                #QCPDuals
                if not(self.isContinuous()) or (
                     'noduals' in self.options and self.options['noduals']):
                        m.setParam('QCPDual',0)
                else:
                        m.setParam('QCPDual',1)
                #--------------------#
                #  call the solver   #
                #--------------------#                
                
                import time
                tstart = time.time()
                
                try:
                        m.optimize()
                except Exception as ex:
                        if str(ex).startswith('Objective Q not PSD'):
                                raise NonConvexError('Error raised during solve. Problem is nonconvex')
                        else:
                                print "Exception raised during solve"
                tend = time.time()
        
                self.gurobi_Instance = m
                
                status = None
                for st in dir(grb.GRB.Status):
                        if st[0]<>'_':
                                if  m.status == eval('grb.GRB.'+st):
                                        status = st
                if status is None:
                        import warnings
                        warnings.warn('gurobi status not found')
                        status = m.status
                        if self.options['verbose']>0:
                                print "\033[1;31m*** gurobi status not found \033[0m"
                
                #----------------------#
                # retrieve the primals #
                #----------------------#
                primals = {}
                obj = m.getObjective().getValue()
                if 'noprimals' in self.options and self.options['noprimals']:
                        pass
                else:
                        #primals
                        try:
                                for var in self.variables.values():
                                        value = []
                                        sz_var = var.endIndex - var.startIndex
                                        for i in range(sz_var):
                                                name = var.name + '_' + str(i)
                                                xi=m.getVarByName(name)
                                                value.append(xi.X)
                                        if var.vtype=='symmetric':
                                                value=svecm1(cvx.matrix(value)) #value was the svec
                                                                                #representation of X
                                                                                    
                                        primals[var.name] = cvx.matrix(value,var.size)
                                
                        except Exception as ex:
                                import warnings
                                warnings.warn('error while retrieving primals')
                                primals = {}
                                obj = None
                                if self.options['verbose']>0:
                                        print "\033[1;31m*** Primal Solution not found\033[0m"

                        
                #--------------------#
                # retrieve the duals #
                #--------------------#
                
                duals = [] 
                if not(self.isContinuous()) or (
                     'noduals' in self.options and self.options['noduals']):
                        pass
                else:
                        try:
                                seen_bounded_vars = []
                                for k,constr in enumerate(self.constraints):
                                        if constr.typeOfConstraint[:3] == 'lin':
                                                dim = constr.Exp1.size[0] * constr.Exp1.size[1]
                                                dual_values = [None] * dim
                                                for (i,name,b,v) in self.grb_boundcons[k]:
                                                        xj = self.gurobi_Instance.getVarByName(name).X
                                                        if ((b=='=') or abs(xj-b)<1e-7) and (name not in seen_bounded_vars):
                                                                #does j appear in another equality constraint ?
                                                                if b!='=':
                                                                       boundsj=[b0 for k0 in range(len(self.constraints))
                                                                                       for (i0,name0,b0,v0) in self.grb_boundcons[k0]
                                                                                       if name0==name]
                                                                       if '=' in boundsj:
                                                                               dual_values[i]=0. #dual will be set later, only for the equality case
                                                                               continue
                                                                else: #equality
                                                                        seen_bounded_vars.append(name)
                                                                        du=  self.gurobi_Instance.getVarByName(name).RC/v
                                                                        dual_values[i]=du
                                                                        continue
                                                                #what kind of inequality ?
                                                                du=self.gurobi_Instance.getVarByName(name).RC
                                                                if (((v>0 and constr.typeOfConstraint[3]=='<') or
                                                                    (v<0 and constr.typeOfConstraint[3]=='>')) and
                                                                    du>0):#upper bound
                                                                        seen_bounded_vars.append(name)
                                                                        dual_values[i]=(du/abs(v))
                                                                elif (((v>0 and constr.typeOfConstraint[3]=='>') or
                                                                     (v<0 and constr.typeOfConstraint[3]=='<')) and
                                                                     du<0):#lower bound
                                                                        seen_bounded_vars.append(name)
                                                                        dual_values[i]=(-du/abs(v))
                                                                else:
                                                                        dual_values[i]=0. #unactive constraint
                                                        else:
                                                                dual_values[i]=0.
                                                #rows with other constraints
                                                for i in range(len(dual_values)):
                                                        if dual_values[i] is None:
                                                                du = m.getConstrByName(
                                                                        'lin'+str(k)+'_'+str(i)).pi
                                                                if constr.typeOfConstraint[3]=='>':
                                                                        dual_values[i] = -du
                                                                else:
                                                                        dual_values[i] = du
                                                        
                                                duals.append(cvx.matrix(dual_values))
                                                
                                        elif constr.typeOfConstraint == 'SOcone':
                                                dual_values=[]
                                                dual_values.append(
                                                        m.getConstrByName('lintmp_rhs_'+str(k)+'_0').pi)
                                                dim = constr.Exp1.size[0] * constr.Exp1.size[1]
                                                for i in range(dim):
                                                        dual_values.append(
                                                        -m.getConstrByName('lintmp_lhs_'+str(k)+'_'+str(i)).pi)
                                                duals.append(cvx.matrix(dual_values))
                                        
                                        elif constr.typeOfConstraint == 'RScone':
                                                dual_values=[]
                                                dual_values.append(
                                                        m.getConstrByName('lintmp_rhs_'+str(k)+'_0').pi)
                                                dim = 1 + constr.Exp1.size[0] * constr.Exp1.size[1]
                                                for i in range(dim):
                                                        dual_values.append(
                                                        -m.getConstrByName('lintmp_lhs_'+str(k)+'_'+str(i)).pi)
                                                duals.append(cvx.matrix(dual_values))
                                        
                                        else:
                                                if self.options['verbose']>0:
                                                        print 'duals for this type of constraint not supported yet'
                                                duals.append(None)

                        except Exception as ex:
                                if self.options['verbose']>0:
                                        print "\033[1;31m*** Dual Solution not found\033[0m"
                #-----------------#
                # return statement#
                #-----------------#             
                
                sol = {'gurobi_model':m, 'status':status, 'time': tend - tstart}
                
                return (primals,duals,obj,sol)

        def _mosek_solve(self):
                """
                Solves the problem with mosek
                """
                
                #----------------------------#
                #  LOAD MOSEK OR MOSEK 7     #
                #----------------------------#
                
                if self.options['solver'] == 'mosek6': #force to use version 6.0 of mosek.
                        import mosek as mosek
                        version7 = not(hasattr(mosek,'cputype'))
                        if version7:
                                raise ImportError("I couldn't find mosek 6.0; the package named mosek is the v7.0")
                else: #try to load mosek7, else use the default mosek package (which can be any version)
                        try:
                                import mosek7 as mosek
                        except ImportError:
                                try:
                                        import mosek as mosek
                                        version7 = not(hasattr(mosek,'cputype')) #True if this is the version 7 of MOSEK
                                        if self.options['solver'] == 'mosek7' and not(version7):
                                                print "\033[1;31m mosek7 not found. using default mosek instead.\033[0m"
                                except:
                                        raise ImportError('mosek library not found')

                version7 = not(hasattr(mosek,'cputype')) #True if this is the version 7 of MOSEK
                                        
                #-------------------------------#
                #  Can we solve it with mosek ? #
                #-------------------------------#
                if self.type in ('unknown type','MISDP','GP'):
                        raise NotAppropriateSolverError("'mosek' cannot solve problems of type {0}".format(self.type))
                
                elif (self.type in ('SDP','ConeP')) and not(version7):
                        raise NotAppropriateSolverError("This version of mosek does not support SDP. Try with mosek v7.0")
                
                elif self.type in ('Mixed (SDP+quad)','Mixed (SOCP+quad)','Mixed (MISOCP+quad)','MIQCP','MIQP'):
                        raise QuadAsSocpError('Please convert the quadratic constraints as cone constraints '+
                                                'with the function convert_quad_to_socp().')
                                                
                #----------------------------#
                #  create the mosek instance #
                #----------------------------#           
                                        
                                        
                self._make_mosek_instance()
                self.last_updated_constraint=self.countCons
                task=self.msk_task
                
                if self.options['verbose']>0:
                        if version7:
                                print '-----------------------------------'
                                print '         MOSEK version 7'
                                print '-----------------------------------'
                        else:
                                print '-----------------------------------'
                                print '            MOSEK solver'
                                print '-----------------------------------'
                
                #---------------------#
                #  setting parameters #
                #---------------------# 
                
                #tolerance (conic + LP interior points)
                task.putdouparam(mosek.dparam.intpnt_tol_dfeas,self.options['tol'])
                task.putdouparam(mosek.dparam.intpnt_tol_pfeas,self.options['tol'])
                task.putdouparam(mosek.dparam.intpnt_tol_mu_red,self.options['tol'])
                task.putdouparam(mosek.dparam.intpnt_tol_rel_gap,self.options['tol'])
                
                task.putdouparam(mosek.dparam.intpnt_co_tol_dfeas,self.options['tol'])
                task.putdouparam(mosek.dparam.intpnt_co_tol_pfeas,self.options['tol'])
                task.putdouparam(mosek.dparam.intpnt_co_tol_mu_red,self.options['tol'])
                task.putdouparam(mosek.dparam.intpnt_co_tol_rel_gap,self.options['tol'])
                
                #tolerance (interior points)
                task.putdouparam(mosek.dparam.mio_tol_rel_gap,self.options['gaplim'])
                
                
                #maxiters
                if not(self.options['maxit'] is None):
                        task.putintparam(mosek.iparam.intpnt_max_iterations,self.options['maxit'])
                        task.putintparam(mosek.iparam.sim_max_iterations,self.options['maxit'])
                
                #lpmethod
                if not self.options['lp_node_method'] is None:
                        if self.options['lp_node_method']=='interior':
                                task.putintparam(mosek.iparam.mio_node_optimizer,mosek.optimizertype.intpnt)
                        elif self.options['lp_node_method']=='psimplex':
                                task.putintparam(mosek.iparam.mio_node_optimizer,mosek.optimizertype.primal_simplex)
                        elif self.options['lp_node_method']=='dsimplex':
                                task.putintparam(mosek.iparam.mio_node_optimizer,mosek.optimizertype.dual_simplex)
                        else:
                                raise Exception('unexpected value for option lp_node_method')
                if not self.options['lp_root_method'] is None:
                        if self.options['lp_root_method']=='interior':
                                task.putintparam(mosek.iparam.mio_root_optimizer,mosek.optimizertype.intpnt)
                                if self.type=='LP':
                                        task.putintparam(mosek.iparam.optimizer,mosek.optimizertype.intpnt)
                        elif self.options['lp_root_method']=='psimplex':
                                task.putintparam(mosek.iparam.mio_root_optimizer,mosek.optimizertype.primal_simplex)
                                if self.type=='LP':
                                        task.putintparam(mosek.iparam.optimizer,mosek.optimizertype.primal_simplex)
                        elif self.options['lp_root_method']=='dsimplex':
                                task.putintparam(mosek.iparam.mio_root_optimizer,mosek.optimizertype.dual_simplex)
                                if self.type=='LP':
                                        task.putintparam(mosek.iparam.optimizer,mosek.optimizertype.dual_simplex)
                        else:
                                raise Exception('unexpected value for option lp_root_method')
                
                if not self.options['timelimit'] is None:
                        task.putdouparam(mosek.dparam.mio_max_time,self.options['timelimit'])
                        task.putdouparam(mosek.dparam.optimizer_max_time,self.options['timelimit'])
                        #task.putdouparam(mosek.dparam.mio_max_time_aprx_opt,self.options['timelimit'])
                else:
                        task.putdouparam(mosek.dparam.mio_max_time,-1.0)
                        task.putdouparam(mosek.dparam.optimizer_max_time,-1.0)
                        #task.putdouparam(mosek.dparam.mio_max_time_aprx_opt,-1.0)
                
                #number feasible solutions
                if not self.options['nbsol'] is None:
                        task.putintparam(mosek.iparam.mio_max_num_solutions,self.options['nbsol'])
                        
                #hotstart
                if self.options['hotstart']:
                        task.putintparam(mosek.iparam.mio_construct_sol,mosek.onoffkey.on)
                
                
                for par,val in self.options['mosek_params'].iteritems():
                        try:
                                mskpar=eval('mosek.iparam.'+par)
                                task.putintparam(mskpar,val)
                        except AttributeError:
                                try:
                                        mskpar=eval('mosek.dparam.'+par)
                                        task.putdouparam(mskpar,val)
                                except AttributeError:
                                        raise Exception('unknown mosek parameter')
                                
                
                #--------------------#
                #  call the solver   #
                #--------------------# 
                
                import time
                tstart = time.time()
                
                #optimize
                try:
                        task.optimize()
                except mosek.Error as ex:
                        #catch non-convexity exception
                        if self.numberQuadConstraints>0 and (str(ex)=='(0) ' or
                                                             str(ex).startswith('(1296)') or
                                                             str(ex).startswith('(1295)')
                                                             ):
                                raise NonConvexError('Error raised during solve. Problem nonconvex ?')
                        else:
                                print "Error raised during solve"
                                
                tend = time.time()                
                
                # Print a summary containing information
                # about the solution for debugging purposes
                task.solutionsummary(mosek.streamtype.msg)
                prosta = []
                solsta = []

                if self.is_continuous():
                        if not(self.options['lp_root_method'] is None) and (
                          self.options['lp_root_method'].endswith('simplex')):
                                soltype=mosek.soltype.bas
                        else:
                                soltype=mosek.soltype.itr
                        intg=False
                else:
                        soltype=mosek.soltype.itg
                        intg=True

                if version7:
                        solsta = task.getsolsta(soltype)
                else:
                        [prosta,solsta] = task.getsolutionstatus(soltype)
                status = repr(solsta)
                #----------------------#
                # retrieve the primals #
                #----------------------#
                #OBJ
                try:
                        obj = task.getprimalobj(soltype)
                except Exception as ex:
                        obj=None
                        if self.options['verbose']>0:
                                print "\033[1;31m*** Primal Solution not found\033[0m"

                #PRIMAL VARIABLES
                primals={}
                
                if 'noprimals' in self.options and self.options['noprimals']:
                        pass
                else:
                        if self.options['verbose']>0:
                                print 'Solution status is ' +repr(solsta)
                        try:
                                # Output a solution
                                indices = [(v.startIndex,v.endIndex,v) for v in self.variables.values()]
                                indices = sorted(indices)
                                if self.options['handleBarVars']:
                                        idxsdpvars=[(si,ei) for (si,ei,v) in indices[::-1] if v.semiDef]
                                        indsdpvar = [i for i,cons in
                                                        enumerate([cs for cs in self.constraints if cs.typeOfConstraint.startswith('sdp')])
                                                        if cons.semidefVar]
                                        isdpvar = 0
                                else:
                                        idxsdpvars=[]
                                for si,ei,var in indices:
                                        if self.options['handleBarVars'] and var.semiDef:
                                                #xjbar = np.zeros(int((var.size[0]*(var.size[0]+1))/2),float)
                                                xjbar = [0.] * int((var.size[0]*(var.size[0]+1))/2)
                                                task.getbarxj(mosek.soltype.itr,indsdpvar[isdpvar],xjbar)
                                                xjbar = ltrim1(cvx.matrix(xjbar))
                                                primals[var.name]=cvx.matrix(xjbar,var.size)
                                                isdpvar += 1
                                                
                                        else:
                                                #xx = np.zeros((ei-si),float)
                                                xx = [0.] * (ei-si) #list instead of np.zeros to avoid PEEP 3118 buffer warning
                                                (nsi,eim),_,_ = self._separate_linear_cons([si,ei-1],[0,0],idxsdpvars)
                                                task.getsolutionslice(soltype,mosek.solitem.xx, nsi,eim+1, xx)
                                                scaledx = [(j,v) for (j,v) in self.msk_scaledcols.iteritems() if j>=si and j<ei]
                                                for (j,v) in scaledx: #do the change of variable the other way around.
                                                        xx[j-si]/=v
                                                if var.vtype=='symmetric':
                                                        xx=svecm1(cvx.matrix(xx))
                                                primals[var.name]=cvx.matrix(xx,var.size)
                                
                                
                                """OLD VERSION, but too slow
                                xx = np.zeros(self.numberOfVars, float)
                                task.getsolutionslice(soltype,
                                        mosek.solitem.xx, 0,self.numberOfVars, xx)

                                for var in self.variables.keys():
                                        si=self.variables[var].startIndex
                                        ei=self.variables[var].endIndex
                                        varvect=xx[si:ei]
                                        if self.variables[var].vtype=='symmetric':
                                                varvect=svecm1(cvx.matrix(varvect)) #varvect was the svec
                                                                                #representation of X
                                        primals[var]=cvx.matrix(varvect, self.variables[var].size)
                                """
                        except Exception as ex:
                                primals={}
                                obj=None
                                if self.options['verbose']>0:
                                        print "\033[1;31m*** Primal Solution not found\033[0m"

                #--------------------#
                # retrieve the duals #
                #--------------------#
                duals=[]
                if intg or ('noduals' in self.options and self.options['noduals']):
                        pass
                else:
                        try:
                                if self.options['handleBarVars']:
                                        idvarcone = int(_bsum([(var.endIndex-var.startIndex)
                                            for var in self.variables.values() if not(var.semiDef)]))
                                else:
                                        idvarcone=self.numberOfVars #index of variables in cone
                                
                                idconin=0 #index of equality constraint in mosekcons (without fixed vars)
                                idin=0 #index of inequality constraint in cvxoptVars['Gl']
                                idcone=0 #number of seen cones
                                idsdp = 0 #number of seen sdp cons
                                szcones = [((cs.Exp1.size[0]*cs.Exp1.size[1] + 2) if cs.Exp3 else (cs.Exp1.size[0]*cs.Exp1.size[1] + 1))
                                                for cs in self.constraints
                                                if cs.typeOfConstraint.endswith('cone')]
                                
                                seen_bounded_vars = []
                                
                                #now we parse the constraints
                                for k,cons in enumerate(self.constraints):
                                        #conic constraint
                                        if cons.typeOfConstraint[2:]=='cone':
                                                szcone=szcones[idcone]
                                                fxd = self.msk_fxdconevars[idcone]
                                                #v=np.zeros(szcone,float) 
                                                v= [0.] * (szcone - len(fxd))
                                                task.getsolutionslice(soltype,mosek.solitem.snx,
                                                                idvarcone,idvarcone+len(v),v)
                                                for i,j in fxd:
                                                        vj=[0.]
                                                        task.getsolutionslice(soltype,mosek.solitem.snx,
                                                                j,j+1,vj)
                                                        v.insert(i,vj[0])
                                                
                                                if cons.typeOfConstraint.startswith('SO'):
                                                        duals.append(cvx.matrix(v))
                                                        duals[-1][0]=-duals[-1][0]
                                                else:
                                                        vr = [-0.25*v[0] -0.5*v[1]] + [0.5*vi for vi in v[2:]] + [-0.25*v[0] +0.5*v[1]]
                                                        duals.append(cvx.matrix(vr))
                                                idvarcone+=szcone-len(fxd)
                                                idconin+=szcone-len(fxd)
                                                idcone+=1
                                        
                                        elif self.constraints[k].typeOfConstraint=='lin=':
                                                szcons=int(np.product(self.constraints[k].Exp1.size))
                                                fxd=self.msk_fxd[k]
                                                #v=np.zeros(szcons-len(fxd),float)
                                                v = [0.] * (szcons-len(fxd))
                                                if len(v)>0:
                                                        task.getsolutionslice(soltype,mosek.solitem.y,
                                                                idconin,idconin+szcons-len(fxd),v)
                                                for (l,var,coef) in fxd: #dual of fixed var constraints
                                                        duu = [0.]
                                                        dul = [0.]
                                                        #duu=np.zeros(1,float)
                                                        #dul=np.zeros(1,float)
                                                        task.getsolutionslice(soltype,mosek.solitem.sux,
                                                                                var,var+1,duu)
                                                        task.getsolutionslice(soltype,mosek.solitem.slx,
                                                                                var,var+1,dul)
                                                        if (var not in seen_bounded_vars):
                                                                v.insert(l,(dul[0]-duu[0])/coef)
                                                                seen_bounded_vars.append(var)
                                                        else:
                                                                v.insert(l,0.)
                                                duals.append(cvx.matrix(v))
                                                idin+=szcons
                                                idconin+=(szcons-len(fxd))
                                                
                                        elif cons.typeOfConstraint[:3]=='lin':#inequality
                                                szcons=int(np.product(cons.Exp1.size))
                                                fxd=self.msk_fxd[k]
                                                #v=np.zeros(szcons-len(fxd),float)
                                                v=[0.] * (szcons-len(fxd))
                                                if len(v)>0:
                                                        task.getsolutionslice(soltype,mosek.solitem.y,
                                                                idconin,idconin+szcons-len(fxd),v)
                                                if cons.typeOfConstraint[3]=='>':
                                                        v = [-vi for vi in v]
                                                for (l,var,coef) in fxd: #dual of simple bound constraints
                                                        #du=np.zeros(1,float)
                                                        du = [0.]
                                                        bound = (cons.Exp2 - cons.Exp1).constant
                                                        if bound is None:
                                                                bound = 0
                                                        elif cons.typeOfConstraint[3]=='>':
                                                                bound = -bound[l]/float(coef)
                                                        else:
                                                                bound = bound[l]/float(coef)
                                                       
                                                        bk,bl,bu=task.getbound(mosek.accmode.var,var)
                                                        duu = [0.]
                                                        dul = [0.]
                                                        #duu=np.zeros(1,float)
                                                        #dul=np.zeros(1,float)
                                                        task.getsolutionslice(soltype,mosek.solitem.sux,
                                                                                var,var+1,duu)
                                                        task.getsolutionslice(soltype,mosek.solitem.slx,
                                                                                var,var+1,dul)
                                                        
                                                        if coef>0: #upper bound
                                                                if bound==bu and (var not in seen_bounded_vars) and(
                                                                    abs(duu[0])>1e-8
                                                                    and abs(dul[0])<1e-5
                                                                    and abs(duu[0])>abs(dul[0])): #active bound:
                                                                        v.insert(l,-duu[0]/coef)
                                                                        seen_bounded_vars.append(var)
                                                                else:
                                                                        v.insert(l,0.) #inactive bound, or active already seen
                                                        else:   #lower bound
                                                                if bound==bl and (var not in seen_bounded_vars) and(
                                                                    abs(dul[0])>1e-8
                                                                    and abs(duu[0])<1e-5
                                                                    and abs(dul[0])>abs(duu[0])): #active bound
                                                                        v.insert(l,dul[0]/coef)
                                                                        seen_bounded_vars.append(var)
                                                                else:
                                                                        v.insert(l,0.) #inactive bound, or active already seen
                                                duals.append(cvx.matrix(v))
                                                idin+=szcons
                                                idconin+=(szcons-len(fxd))
                                                
                                        elif cons.typeOfConstraint[:3]=='sdp':
                                                sz = cons.Exp1.size
                                                xx = [0.] * ((sz[0]*(sz[0]+1))/2)
                                                #xx=np.zeros((sz[0]*(sz[0]+1))/2,float)
                                                task.getbarsj(mosek.soltype.itr,idsdp,xx)
                                                idsdp+=1
                                                M = ltrim1(cvx.matrix(xx))
                                                duals.append(-cvx.matrix(M))
                                        else:
                                                        if self.options['verbose']>0:
                                                                print('dual for this constraint is not handled yet')
                                                        duals.append(None)
                                if self.objective[0]=='min':
                                        duals=[-d for d in duals]
                        except Exception as ex:
                                if self.options['verbose']>0:
                                        print "\033[1;31m*** Dual Solution not found\033[0m"
                                duals = []
                #-----------------#
                # return statement#
                #-----------------#  
                #OBJECTIVE
                sol = {'mosek_task':task,'status':status, 'time':tend - tstart}
                
                return (primals,duals,obj,sol)                
        
                
       
       
        def _zibopt_solve(self):
                """
                Solves the problem with the zib optimization suite
                """
                
                #-------------------------------#
                #  Can we solve it with zibopt? #
                #-------------------------------#
                if self.type in ('unknown type','GP','SDP','ConeP','Mixed (SDP+quad)','MISDP'):
                        raise NotAppropriateSolverError("'zibopt' cannot solve problems of type {0}".format(self.type))
                
                
                #-----------------------------#
                #  create the zibopt instance #
                #-----------------------------#
                if self.options['onlyChangeObjective']:
                        if self.scip_solver is None:
                                raise Exception('option is only available when scip_solver has been defined before')
                        #define scip_obj
                        newobj=self.objective[1]
                        x=self.scip_vars
                        ob=0
                        
                        if isinstance(newobj,QuadExp):
                                for i,j in newobj.quad:
                                        si,ei=i.startIndex,i.endIndex
                                        sj,ej=j.startIndex,j.endIndex
                                        Qij=newobj.quad[i,j]
                                        if not isinstance(Qij,cvx.spmatrix):
                                                Qij=cvx.sparse(Qij)
                                        for ii,jj,vv in zip(Qij.I,Qij.J,Qij.V):
                                                ob+=vv*x[ii+si]*x[jj+sj]
                                newobj=newobj.aff
                                        
                        if not(newobj is None):
                                for v,fac in newobj.factors.iteritems():
                                        if not isinstance(fac,cvx.spmatrix):
                                                fac=cvx.sparse(fac)
                                        sv=v.startIndex
                                        for jj,vv in zip(fac.J,fac.V):
                                                ob+=vv*x[jj+sv]
                                if not(newobj.constant is None):
                                        ob+=newobj.constant[0]
                        self.scip_obj = ob
                        
                else:
                        self._make_zibopt()
                        self.last_updated_constraint=self.countCons
                
                timelimit=10000000.
                gaplim=self.options['tol']
                nbsol=-1
                if not self.options['timelimit'] is None:
                        timelimit=self.options['timelimit']
                if not(self.options['gaplim'] is None or self.is_continuous()):
                        gaplim=self.options['gaplim']
                if not self.options['nbsol'] is None:
                        nbsol=self.options['nbsol']
                
                #--------------------#
                #  call the solver   #
                #--------------------#
                import time
                tstart = time.time()
                
                if self.objective[0]=='max':
                        if self.scip_obj is None:
                                sol=self.scip_solver.maximize(time=timelimit,
                                                        gap=gaplim,
                                                        nsol=nbsol)
                        else:#quadratic obj
                                sol=self.scip_solver.maximize(time=timelimit,
                                                        gap=gaplim,
                                                        nsol=nbsol,
                                                        objective=self.scip_obj)
                else:
                        if self.scip_obj is None:
                                sol=self.scip_solver.minimize(time=timelimit,
                                                        gap=gaplim,
                                                        nsol=nbsol)
                        else:#quadratic obj
                                sol=self.scip_solver.minimize(time=timelimit,
                                                        gap=gaplim,
                                                        nsol=nbsol,
                                                        objective=self.scip_obj)
                tend = time.time()
                
                if sol.optimal:
                        status='optimal'
                elif sol.infeasible:
                        status='infeasible'
                elif sol.unbounded:
                        status='unbounded'
                elif sol.inforunbd:
                        status='infeasible or unbounded'
                else:
                        status='unknown'
                        
                if self.options['verbose']>0:
                        print 'zibopt solution status: '+status
                
                #----------------------#
                # retrieve the primals #
                #----------------------#
                primals = {}
                obj=sol.objective
                if 'noprimals' in self.options and self.options['noprimals']:
                        pass
                else:
                        try:
                                val=sol.values()
                                primals={}
                                for var in self.variables.keys():
                                        si=self.variables[var].startIndex
                                        ei=self.variables[var].endIndex
                                        varvect=self.scip_vars[si:ei]
                                        value = [val[v] for v in varvect]
                                        if self.variables[var].vtype=='symmetric':
                                                value=svecm1(cvx.matrix(value)) #value was the svec
                                                                                    #representation of X
                                        primals[var]=cvx.matrix(value,
                                                self.variables[var].size)
                        except Exception as ex:
                                primals={}
                                obj = None
                                if self.options['verbose']>0:
                                        print "\033[1;31m*** Primal Solution not found\033[0m"

                #----------------------#
                # retrieve the duals #
                #----------------------#
                
                #not available by python-zibopt (yet ? )
                duals = []
                #------------------#
                # return statement #
                #------------------#  
                
                solt={}
                solt['zibopt_sol']=sol
                solt['status']=status
                solt['time'] = tend - tstart
                return (primals,duals,obj,solt)
                
                
        def _sqpsolve(self,options):
                """
                Solves the problem by sequential Quadratic Programming.
                """
                import copy
                for v in self.variables:
                        if self.variables[v].value is None:
                                self.set_var_value(v,cvx.uniform(self.variables[v].size))
                #lower the display level for mosek                
                self.options['verbose']-=1
                oldvar=self._eval_all()
                subprob=copy.deepcopy(self)
                if self.options['verbose']>0:
                        print('solve by SQP method with proximal convexity enforcement')
                        print('it:     crit\t\tproxF\tstep')
                        print('---------------------------------------')
                converged=False
                k=1
                while not converged:
                        obj,grad,hess=self.objective[1].fun(self.objective[1].Exp.eval())
                        diffExp=self.objective[1].Exp-self.objective[1].Exp.eval()
                        quadobj0=obj+grad.T*diffExp+0.5*diffExp.T*hess*diffExp
                        proxF=self.options['step_sqp']
                        #VARIANT IN CONSTRAINTS: DO NOT FORCE CONVEXITY...
                        #for v in subprob.variables.keys():
                        #        x=subprob.get_varExp(v)
                        #        x0=self.get_variable(v).eval()
                        #        subprob.add_constraint((x-x0).T*(x-x0)<0.5)
                        solFound=False
                        while (not solFound):
                                if self.objective[0]=='max':
                                        quadobj=quadobj0-proxF*abs(diffExp)**2 #(proximal + force convexity)
                                else:
                                        quadobj=quadobj0+proxF*abs(diffExp)**2 #(proximal + force convexity)
                                subprob=copy.deepcopy(self)                                
                                subprob.set_objective(self.objective[0],quadobj)
                                if self.options['harmonic_steps'] and k>1:
                                        for v in subprob.variables.keys():
                                                x=subprob.get_varExp(v)
                                                x0=self.get_variable(v).eval()
                                                subprob.add_constraint((x-x0).T*(x-x0)<(10./float(k-1)))
                                try:
                                        sol=subprob.solve()
                                        solFound=True
                                except Exception as ex:
                                        if str(ex)[:6]=='(1296)': #function not convex
                                                proxF*=(1+cvx.uniform(1))
                                        else:
                                                #reinit the initial verbosity
                                                self.options['verbose']+=1
                                                raise
                        if proxF>=100*self.options['step_sqp']:
                                #reinit the initial verbosity
                                self.options['verbose']+=1
                                raise Exception('function not convex before proxF reached 100 times the initial value')

                        for v in subprob.variables:
                                self.set_var_value(v,subprob.get_valued_variable(v))
                        newvar=self._eval_all()
                        step=np.linalg.norm(newvar-oldvar)
                        if isinstance(step,cvx.matrix):
                                step=step[0]
                        oldvar=newvar
                        if self.options['verbose']>0:
                                if k==1:
                                        print('  {0}:         --- \t{1:6.3f} {2:10.4e}'.format(k,proxF,step))
                                else:
                                        print('  {0}:   {1:16.9e} {2:6.3f} {3:10.4e}'.format(k,obj,proxF,step))
                        k+=1
                        #have we converged ?
                        if step<self.options['tol']:
                                converged=True
                        if k>self.options['maxit']:
                                converged=True
                                print('Warning: no convergence after {0} iterations'.format(k))

                #reinit the initial verbosity
                self.options['verbose']+=1
                sol['lastStep']=step
                return sol
                
        def what_type(self):
                
                iv= [v for v in self.variables.values() if v.vtype not in ('continuous','symmetric') ]
                #continuous problem
                if len(iv)==0:
                        #general convex
                        if not(self.objective[1] is None) and isinstance(self.objective[1],GeneralFun):
                                return 'general-obj'
                        #GP
                        if self.numberLSEConstraints>0:
                                if (self.numberConeConstraints ==0
                                and self.numberQuadConstraints == 0
                                and self.numberSDPConstraints == 0):
                                        return 'GP'
                                else:
                                        return 'unknown type'
                        #SDP
                        if self.numberSDPConstraints>0:
                                if (self.numberConeConstraints ==0
                                and self.numberQuadConstraints == 0):
                                        return 'SDP'
                                elif self.numberQuadConstraints == 0:
                                        return 'ConeP'
                                else:
                                        return 'Mixed (SDP+quad)'
                        #SOCP
                        if self.numberConeConstraints > 0:
                                if self.numberQuadConstraints == 0:
                                        return 'SOCP'
                                else:
                                        return 'Mixed (SOCP+quad)'

                        #quadratic problem
                        if self.numberQuadConstraints>0:
                                if any([cs.typeOfConstraint=='quad' for cs in self.constraints]):
                                        return 'QCQP'
                                else:
                                        return 'QP'
                                
                        return 'LP'
                else:
                        if not(self.objective[1] is None) and isinstance(self.objective[1],GeneralFun):
                                return 'unknown type'
                        if self.numberLSEConstraints>0:
                                return 'unknown type'
                        if self.numberSDPConstraints>0:
                                return 'MISDP'
                        if self.numberConeConstraints > 0:
                                if self.numberQuadConstraints == 0:
                                        return 'MISOCP'
                                else:
                                        return 'Mixed (MISOCP+quad)'
                        if self.numberQuadConstraints>0:
                                if any([cs.typeOfConstraint=='quad' for cs in self.constraints]):
                                        return 'MIQCP'
                                else:
                                        return 'MIQP'
                        return 'MIP' #(or simply IP)
                        
        def set_type(self,value):
                raise AttributeError('type is not writable')
        
        def del_type(self):
                raise AttributeError('type is not writable')
        
        type=property(what_type,set_type,del_type)
        """Type of Optimization Problem ('LP', 'MIP', 'SOCP', 'QCQP',...)"""
        
        
        def solver_selection(self):
                """Selects an appropriate solver for this problem
                and sets the option ``'solver'``.
                """
                tp=self.type
                if tp == 'LP':
                        order=['cplex','gurobi','mosek7','mosek6','zibopt','cvxopt','smcp']
                elif tp in ('QCQP,QP'):
                        order=['cplex','mosek7','mosek6','gurobi','cvxopt','zibopt']
                elif tp == 'SOCP':
                        order=['mosek7','mosek6','cplex','gurobi','cvxopt','smcp','zibopt']
                elif tp == 'SDP':
                        order=['mosek7','cvxopt','smcp']
                elif tp == 'ConeP':
                        order=['mosek7','cvxopt','smcp']
                elif tp == 'GP':
                        order=['cvxopt']
                elif tp == 'general-obj':
                        order=['cplex','mosek7','mosek6','gurobi','zibopt','cvxopt','smcp']
                elif tp in ('MIP','MIQCP','MIQP'):
                        order=['cplex','gurobi','mosek7','mosek6','zibopt']
                elif tp == 'Mixed (SOCP+quad)':
                        order=['mosek7','mosek6','cplex','gurobi','cvxopt','smcp']
                elif tp in ('MISOCP','Mixed (MISOCP+quad)'):
                        order=['mosek7','mosek6','cplex','gurobi']
                elif tp == 'Mixed (SDP+quad)':
                        order=['mosek7','cvxopt','smcp']
                else:
                        raise Exception('no solver available for problem of type {0}'.format(tp))
                avs=available_solvers()
                for sol in order:
                        if sol in avs:
                                self.set_option('solver',sol)
                                return
                #not found
                raise NotAppropriateSolverError('no solver available for problem of type {0}'.format(tp))
                
                
        def write_to_file(self,filename,writer='picos'):
                """
                This function writes the problem to a file.
                
                :param filename: The name of the file where the problem will be saved. The
                                 extension of the file (if provided) indicates the format
                                 of the export:
                                 
                                        * ``'.lp'``: `LP format <http://docs.mosek.com/6.0/pyapi/node022.html>`_
                                          . This format handles only linear constraints, unless the writer ``'cplex'``
                                          is used, and the file is saved in the extended
                                          `cplex LP format <http://pic.dhe.ibm.com/infocenter/cplexzos/v12r4/index.jsp?topic=%2Fcom.ibm.cplex.zos.help%2Fhomepages%2Freffileformatscplex.html>`_
                                          
                                        * ``'.mps'``: `MPS format <http://docs.mosek.com/6.0/pyapi/node021.html>`_
                                          (recquires mosek, gurobi or cplex).
                                          
                                        * ``'.opf'``: `OPF format <http://docs.mosek.com/6.0/pyapi/node023.html>`_
                                          (recquires mosek).
                                          
                                        * ``'.dat-s'``: `sparse SDPA format <http://sdpa.indsys.chuo-u.ac.jp/sdpa/download.html#sdpa>`_
                                          This format is suitable to save semidefinite programs (SDP). SOC constraints are
                                          stored as semidefinite constraints with an *arrow pattern*.
                                        
                :type filename: str.
                :param writer: The default writer is ``picos``, which has its own *LP* and
                               *sparse SDPA* write functions. If cplex, mosek or gurobi is installed,
                               the user can pass the option ``writer='cplex'``, ``writer='gurobi'`` or
                               ``writer='mosek'``, and the write function of this solver
                               will be used.                               
                :type writer: str.
                
                .. Warning :: For problems involving a symmetric matrix variable :math:`X`
                              (typically, semidefinite programs), the expressions
                              involving :math:`X` are stored in PICOS as a function of
                              :math:`svec(X)`, the symmetric vectorized form of
                              X (see `Dattorro, ch.2.2.2.1 <http://meboo.convexoptimization.com/Meboo.html>`_).
                              As a result, the symmetric matrix variables
                              are written in :math:`svec()` form in the files created by this function.
                              So if you use another solver to solve
                              a problem that is described in a file created by PICOS, the optimal symmetric variables
                              returned will also be in symmetric vectorized form.
                """
                if self.numberLSEConstraints:
                        raise Exception('gp are not supported')
                if not(self.objective[1] is None) and isinstance(self.objective[1],GeneralFun):
                        raise Exception('general-obj are not supported')       
                
                #automatic extension recognition
                if not(filename[-4:] in ('.mps','.opf') or
                       filename[-3:]=='.lp' or
                       filename[-6:]=='.dat-s' or
                       filename[-7:]=='.dat-sx'):
                        if writer in ('mosek','gurobi'):
                                if (self.numberSDPConstraints >0):
                                        raise Exception('no sdp with mosek/gurobi')
                                if (self.numberConeConstraints + 
                                    self.numberQuadConstraints) ==0:
                                        filename+='.lp'
                                else:
                                        filename+='.mps'
                        elif writer=='cplex':
                                if (self.numberSDPConstraints >0):
                                        raise Exception('no sdp with cplex')
                                else:
                                        filename+='.lp'
                        elif writer=='picos':
                                if (self.numberQuadConstraints >0):
                                        if self.options['convert_quad_to_socp_if_needed']:
                                                pcop=self.copy()
                                                pcop.convert_quad_to_socp()
                                                pcop.write_to_file(filename,writer)
                                                return
                                        else:
                                                raise QuadAsSocpError('no quad constraints in sdpa format.'+
                                                  ' Try to convert to socp with the function convert_quad_to_socp().')
                                if (self.numberConeConstraints + 
                                    self.numberSDPConstraints) ==0:
                                        filename+='.lp'
                                else:
                                        filename+='.dat-s'
                        else:
                                raise Exception('unexpected writer')

                #writer selection [obsolete, since we now give picos as default]
                if writer is None:
                        avs=available_solvers()
                        if filename[-4:]=='.mps':
                                if 'mosek' in avs:
                                        writer='mosek'
                                elif 'gurobi' in avs:
                                        writer='gurobi'
                                else:
                                        raise Exception('no mps writer available')
                        elif filename[-4:]=='.opf':
                                if 'mosek' in avs:
                                        writer='mosek'
                                else:
                                        raise Exception('no opf writer available')
                        elif filename[-3:]=='.lp':
                                if not(self.cplex_Instance is None):
                                        writer='cplex'
                                elif not(self.msk_task is None) and (self.numberConeConstraints + 
                                                                self.numberQuadConstraints) ==0:
                                        writer='mosek'
                                elif not(self.gurobi_Instance is None) and (self.numberConeConstraints + 
                                                                self.numberQuadConstraints) ==0:
                                        writer='gurobi'
                                elif 'cplex' in avs:
                                        writer='cplex'
                                elif 'mosek' in avs and (self.numberConeConstraints + 
                                                                self.numberQuadConstraints) ==0:
                                        writer='mosek'
                                elif 'gurobi' in avs and (self.numberConeConstraints + 
                                                                self.numberQuadConstraints) ==0:
                                        writer='gurobi'
                                else:
                                        writer='picos'
                        elif filename[-6:]=='.dat-s':
                                writer='picos'
                        elif filename[-7:]=='.dat-sx':
                                writer='picos'
                        else:
                                raise Exception('unexpected file extension')
                
                  
                if writer == 'cplex':
                        if self.cplex_Instance is None:
                                self._make_cplex_instance()
                        self.cplex_Instance.write(filename)
                elif writer == 'mosek':
                        if self.msk_task is None:
                                self._make_mosek_instance()
                        self.msk_task.writedata(filename)
                elif writer == 'gurobi':
                        if self.gurobi_Instance is None:
                                self._make_gurobi_instance()
                        self.gurobi_Instance.write(filename)
                elif writer == 'picos':
                        if filename[-3:]=='.lp':
                                self._write_lp(filename)
                        elif filename[-6:]=='.dat-s':
                                self._write_sdpa(filename)
                        elif filename[-7:]=='.dat-sx':
                                self._write_sdpa(filename,True)
                        else:
                                raise Exception('unexpected file extension')
                else:
                        raise Exception('unknown writer')
        
        def _write_lp(self,filename):
                """
                writes problem in  lp format
                """
                #add extension
                if filename[-3:]!='.lp':
                        filename+='.lp'
                #check lp compatibility
                if (self.numberConeConstraints + 
                    self.numberQuadConstraints +
                    self.numberLSEConstraints  +
                    self.numberSDPConstraints) > 0:
                        raise Exception('the picos LP writer only accepts (MI)LP')
                #open file
                f = open(filename,'w')
                f.write("\\* file "+filename+" generated by picos*\\\n")
                #cvxoptVars
                if not any(self.cvxoptVars.values()):
                        self._make_cvxopt_instance()
                #variable names
                varnames={}
                for name,v in self.variables.iteritems():
                        j=0
                        k=0
                        for i in xrange(v.startIndex,v.endIndex):
                                if v.size==(1,1):
                                        varnames[i]=name
                                elif v.size[1]==1:
                                        varnames[i]=name+'('+str(j)+')'
                                        j+=1
                                else:
                                        varnames[i]=name+'('+str(j)+','+str(k)+')'
                                        j+=1
                                        if j==v.size[0]:
                                                k+=1
                                                j=0
                                varnames[i]=varnames[i].replace('[','(')
                                varnames[i]=varnames[i].replace(']',')')
                #affexpr writer
                def affexp_writer(name,indices,coefs):
                        s=''
                        s+=name
                        s+=' : '
                        start=True
                        for (i,v) in zip(indices,coefs):
                                if v>0 and not(start):
                                        s+='+ '
                                s+="%.12g" % v
                                s+=' '
                                s+=varnames[i]
                                #not the first term anymore
                                start = False
                        if not(coefs):
                                s+='0.0 '
                                s+=varnames[0]
                        return s
                
                print 'writing problem in '+filename+'...'
                
                #objective
                if self.objective[0]=='max':
                        f.write("Maximize\n")
                        #max handled directly
                        self.cvxoptVars['c']=-self.cvxoptVars['c']
                else:
                        f.write("Minimize\n")
                I=cvx.sparse(self.cvxoptVars['c']).I
                V=cvx.sparse(self.cvxoptVars['c']).V
                
                f.write(affexp_writer('obj',I,V))
                f.write('\n')
                
                f.write("Subject To\n")
                bounds={}
                #equality constraints:
                Ai,Aj,Av=( self.cvxoptVars['A'].I,self.cvxoptVars['A'].J,self.cvxoptVars['A'].V)
                ijvs=sorted(zip(Ai,Aj,Av))
                del Ai,Aj,Av
                itojv={}
                lasti=-1
                for (i,j,v) in ijvs:
                        if i==lasti:
                                itojv[i].append((j,v))
                        else:
                                lasti=i
                                itojv[i]=[(j,v)]
                ieq=0
                for i,jv in itojv.iteritems():
                        J=[jvk[0] for jvk in jv]
                        V=[jvk[1] for jvk in jv]
                        if len(J)==1:
                                #fixed variable
                                b=self.cvxoptVars['b'][i]/V[0]
                                bounds[J[0]]=(b,b)
                        else:
                                #affine equality
                                b=self.cvxoptVars['b'][i]
                                f.write(affexp_writer('eq'+str(ieq),J,V))
                                f.write(' = ')
                                f.write("%.12g" % b)
                                f.write('\n')
                                ieq+=1
                
                
                #inequality constraints:
                Gli,Glj,Glv=( self.cvxoptVars['Gl'].I,self.cvxoptVars['Gl'].J,self.cvxoptVars['Gl'].V)
                ijvs=sorted(zip(Gli,Glj,Glv))
                del Gli,Glj,Glv
                itojv={}
                lasti=-1
                for (i,j,v) in ijvs:
                        if i==lasti:
                                itojv[i].append((j,v))
                        else:
                                lasti=i
                                itojv[i]=[(j,v)]
                iaff=0
                for i,jv in itojv.iteritems():
                        J=[jvk[0] for jvk in jv]
                        V=[jvk[1] for jvk in jv]
                        if len(J)==1 and (not (i in [t[1] for t in self.cvxoptVars['quadcons']])):
                                #bounded variable
                                if J[0] in bounds:
                                        bl,bu=bounds[J[0]]
                                else:
                                        bl,bu=-INFINITY,INFINITY
                                b=self.cvxoptVars['hl'][i]/V[0]
                                if V[0]>0:
                                        #less than
                                        bu=min(b,bu)
                                if V[0]<0:
                                        #greater than
                                        bl=max(b,bl)
                                bounds[J[0]]=(bl,bu)
                        else:
                                #affine inequality
                                b=self.cvxoptVars['hl'][i]
                                f.write(affexp_writer('in'+str(iaff),J,V))
                                f.write(' <= ')
                                f.write("%.12g" % b)
                                f.write('\n')
                                iaff+=1

                #bounds
                f.write("Bounds\n")
                for i in xrange(self.numberOfVars):
                        if i in bounds:
                                bl,bu=bounds[i]
                        else:
                                bl,bu=-INFINITY,INFINITY
                        if bl == -INFINITY and bu == INFINITY:
                                f.write(varnames[i]+' free')
                        elif bl == bu:
                                f.write(varnames[i]+(" = %.12g" % bl))
                        elif bl < bu:
                                if bl == -INFINITY:
                                        f.write('-inf <= ')
                                else:
                                        f.write("%.12g" % bl)
                                        f.write(' <= ')
                                f.write(varnames[i])
                                if bu == INFINITY:
                                        f.write('<= +inf')
                                else:
                                        f.write(' <= ')
                                        f.write("%.12g" % bu)
                        f.write('\n')

                #general integers
                f.write("Generals\n")
                for name,v in self.variables.iteritems():
                        if v.vtype=='integer':
                                for i in xrange(v.startIndex,v.endIndex):
                                        f.write(varnames[i]+'\n')
                        if v.vtype=='semiint' or v.vtype=='semicont':
                                raise Exception('semiint and semicont variables not handled by this LP writer')
                #binary variables
                f.write("Binaries\n")
                for name,v in self.variables.iteritems():
                        if v.vtype=='binary':
                                for i in xrange(v.startIndex,v.endIndex):
                                        f.write(varnames[i]+'\n')
                f.write("End\n")
                print 'done.'
                f.close()

        
        def _write_sdpa(self,filename,extended=False):
                """
                write a problem to sdpa format
                """
                
                #--------------------#
                # makes the instance #
                #--------------------#
                if not any(self.cvxoptVars.values()):
                        self._make_cvxopt_instance()
                
                
                dims={}
                dims['s']=[int(np.sqrt(Gsi.size[0])) for Gsi in self.cvxoptVars['Gs']]
                dims['l']=self.cvxoptVars['Gl'].size[0]
                dims['q']=[Gqi.size[0] for Gqi in self.cvxoptVars['Gq']]
                G=self.cvxoptVars['Gl']
                h=self.cvxoptVars['hl']
                
                # handle the equalities as 2 ineq for smcp
                if self.cvxoptVars['A'].size[0]>0:
                        G=cvx.sparse([G,self.cvxoptVars['A']]) 
                        G=cvx.sparse([G,-self.cvxoptVars['A']])
                        h=cvx.matrix([h,self.cvxoptVars['b']])
                        h=cvx.matrix([h,-self.cvxoptVars['b']])
                        dims['l']+=(2*self.cvxoptVars['A'].size[0])

                for i in range(len(dims['q'])):
                        G=cvx.sparse([G,self.cvxoptVars['Gq'][i]])
                        h=cvx.matrix([h,self.cvxoptVars['hq'][i]])

                                        
                for i in range(len(dims['s'])):
                        G=cvx.sparse([G,self.cvxoptVars['Gs'][i]])
                        h=cvx.matrix([h,self.cvxoptVars['hs'][i]])

                #Remove the lines in A and b corresponding to 0==0        
                JP=list(set(self.cvxoptVars['A'].I))
                IP=range(len(JP))
                VP=[1]*len(JP)
                
                idx_0eq0 = [i for i in range(self.cvxoptVars['A'].size[0]) if i not in JP]
                
                #is there a constraint of the form 0==a(a not 0) ?
                if any([b for (i,b) in enumerate(self.cvxoptVars['b']) if i not in JP]):
                        raise Exception('infeasible constraint of the form 0=a')
                
                P=cvx.spmatrix(VP,IP,JP,(len(IP),self.cvxoptVars['A'].size[0]))
                self.cvxoptVars['A']=P*self.cvxoptVars['A']
                self.cvxoptVars['b']=P*self.cvxoptVars['b']
                c = self.cvxoptVars['c']
                
                #-----------------------------------------------------------#
                # make A,B,and blockstruct.                                 #
                # This code is a modification of the conelp function in smcp#
                #-----------------------------------------------------------#
                from cvxopt import matrix,sparse,spdiag,spmatrix
                
                Nl = dims['l']
                Nq = dims['q']
                Ns = dims['s']
                if not Nl: Nl = 0

                nblocks = Nl + len(Nq) + len(Ns)

                P_n = Nl+_bsum(Nq)+_bsum(Ns)
                P_m = G.size[1]

                P_A = {}
                P_b = -c
                P_blockstruct = []
                if Nl: P_blockstruct.append(-Nl)
                if extended:
                        for i in Nq: P_blockstruct.append(i*1j)
                else:
                        for i in Nq: P_blockstruct.append(i)
                for i in Ns: P_blockstruct.append(i)

                def tril(X): #lower triangular part
                        I=[]
                        J=[]
                        V=[]
                        for i,j,v in zip(X.I,X.J,X.V):
                                if j<=i:
                                        I.append(i)
                                        J.append(j)
                                        V.append(v)
                        return cvx.spmatrix(V,I,J,X.size)
                                                
                def ind2sub(n,ind): #transform index in col major order into
                                    #a pair of matrix indices
                        I=[]
                        J=[]
                        for i in ind:
                                I.append(i%n)
                                J.append(i//n)
                        return I,J
                        
                
                
                for k in range(P_m+1):
                        if not k==0:
                                v = sparse(G[:,k-1])
                        else:
                                v = +sparse(h)
                        B = []

                        ptr = 0
                        # lin. constraints
                        if Nl:
                                u = v[:Nl]
                                I = u.I
                                B.append(spmatrix(u.V,I,I,(Nl,Nl)))
                                ptr += Nl

                        # SOC constraints
                        for i in xrange(len(Nq)):
                                nq = Nq[i]
                                u0 = v[ptr]
                                u1 = v[ptr+1:ptr+nq]
                                tmp = spmatrix(u1.V,[nq-1 for j in xrange(len(u1))],u1.I,(nq,nq))
                                if not u0 == 0.0:
                                        tmp += spmatrix(u0,xrange(nq),xrange(nq),(nq,nq)) 
                                B.append(tmp)
                                ptr += Nq[i]

                        # SDP constraints
                        for i in xrange(len(Ns)):
                                ns = Ns[i]
                                u = v[ptr:ptr+ns**2]
                                I,J = ind2sub(ns,u.I)
                                tmp = tril(spmatrix(u.V,I,J,(ns,ns)))
                                B.append(tmp)
                                ptr += ns**2

                        #Ai = spdiag(B)
                        #P_A[:,k] = Ai[:]
                        P_A[k]=B

                
                
                #write data
                                
                #add extension
                if extended:
                        if filename[-7:]!='.dat-sx':
                                filename+='.dat-sx'
                else:
                        if filename[-6:]!='.dat-s':
                                filename+='.dat-s'
                #check lp compatibility
                if (self.numberQuadConstraints +
                    self.numberLSEConstraints) > 0:
                        if self.options['convert_quad_to_socp_if_needed']:
                                pcop=self.copy()
                                pcop.convert_quad_to_socp()
                                pcop._write_sdpa(filename,extended)
                                return
                        else:
                                raise QuadAsSocpError('Problem should not have quad or gp constraints. '+
                                        'Try to convert the problem to an SOCP with the function convert_quad_to_socp()')
                #open file
                f = open(filename,'w')
                f.write('"file '+filename+' generated by picos"\n')
                print 'writing problem in '+filename+'...'
                f.write(str(self.numberOfVars)+' = number of vars\n')
                f.write(str(len(P_blockstruct))+' = number of blocs\n')
                #bloc structure
                f.write(str(P_blockstruct).replace('[','(').replace(']',')'))
                f.write(' = BlocStructure\n')
                #c vector (objective)
                f.write(str(list(-P_b)).replace('[','{').replace(']','}'))
                f.write('\n')
                #coefs
                from itertools import izip
                for k,Ak in P_A.iteritems():
                        for b,B in enumerate(Ak):
                                for i,j,v in izip(B.I,B.J,B.V):
                                        f.write('{0}\t{1}\t{2}\t{3}\t{4}\n'.format(
                                                  k,b+1,j+1,i+1,-v))
                
                #binaries an integers in extended format
                if extended:
                        #general integers
                        f.write("Generals\n")
                        for name,v in self.variables.iteritems():
                                if v.vtype=='integer':
                                        for i in xrange(v.startIndex,v.endIndex):
                                                f.write(str(i+1)+'\n')
                                if v.vtype=='semiint' or v.vtype=='semicont':
                                        raise Exception('semiint and semicont variables not handled by this LP writer')
                        #binary variables
                        f.write("Binaries\n")
                        for name,v in self.variables.iteritems():
                                if v.vtype=='binary':
                                        for i in xrange(v.startIndex,v.endIndex):
                                                f.write(str(i+1)+'\n')
                
                print 'done.'
                f.close()
                
        def convert_quad_to_socp(self):
                if self.options['verbose']>0:
                        print 'reformulating quads as socp...'
                for i,c in enumerate(self.constraints):
                        if c.typeOfConstraint=='quad':
                                qd=c.Exp1.quad
                                sqnorm=_quad2norm(qd)
                                self.constraints[i]=sqnorm<-c.Exp1.aff
                                self.numberQuadConstraints-=1
                                self.numberConeConstraints+=1
                                szcone=sqnorm.LR[0].size
                                self.numberConeVars+=(szcone[0]*szcone[1])+2
                if isinstance(self.objective[1],QuadExp):
                        if '_obj_' not in self.variables:
                                obj=self.add_variable('_obj_',1)
                        else:
                                obj=self.get_variable('_obj_')
                        if self.objective[0]=='min':
                                qd=self.objective[1].quad
                                aff=self.objective[1].aff
                                sqnorm=_quad2norm(qd)
                                self.add_constraint(sqnorm<obj-aff)
                                self.set_objective('min',obj)
                        else:
                                qd=(-self.objective[1]).quad
                                aff=self.objective[1].aff
                                sqnorm=_quad2norm(qd)
                                self.add_constraint(sqnorm<aff-obj)
                                self.set_objective('max',obj)
                        #self.numberQuadConstraints-=1 # no ! because numberQuadConstraints is already uptodate affter set_objective()
                if self.numberQuadConstraints>0:
                        raise Exception('there should not be any quadratics left')
                self.numberQuadNNZ=0
                #reset solver instances
                self.cvxoptVars={'c':None,'A':None,'b':None,'Gl':None,
                                'hl':None,'Gq':None,'hq':None,'Gs':None,'hs':None,
                                'F':None,'g':None, 'quadcons': None}
                
                self.gurobi_Instance = None
                self.grbvar = {}
                
                self.cplex_Instance = None
                self.cplex_boundcons = None
                
                self.msk_env=None
                self.msk_task=None

                self.scip_solver = None
                self.scip_vars = None
                self.scip_obj = None
                if self.options['verbose']>0:
                        print 'done.'
                                
                            
        def dualize(self):
                if self.numberLSEConstraints>0:
                        raise DualizationError('GP cannot be dualized by PICOS')
                if not self.is_continuous():
                        raise DualizationError('Mixed integer problems cannot be dualized by picos')
                if self.numberQuadConstraints>0:
                        raise QuadAsSocpError('try to convert the quads as socp before dualizing')
                dual = Problem()
                self._make_cvxopt_instance()
                cc = new_param('cc',self.cvxoptVars['c'])
                lincons = cc
                obj = 0
                #equalities
                Ae = new_param('Ae',self.cvxoptVars['A'])
                be = new_param('be',-self.cvxoptVars['b'])
                if Ae.size[0]>0:
                        mue = dual.add_variable('mue',Ae.size[0])
                        lincons += (Ae.T * mue)
                        obj += be.T * mue
                #inequalities
                Al = new_param('Al',self.cvxoptVars['Gl'])
                bl = new_param('bl',-self.cvxoptVars['hl'])
                if Al.size[0]>0:
                        mul = dual.add_variable('mul',Al.size[0])
                        dual.add_constraint(mul>0)
                        lincons += (Al.T * mul)
                        obj += bl.T * mul
                #soc cons
                i=0
                As,bs,fs,ds,zs,lbda = [],[],[],[],[],[]
                for Gq,hq in zip(self.cvxoptVars['Gq'],self.cvxoptVars['hq']):
                        As.append(new_param('As['+str(i)+']',-Gq[1:,:]))
                        bs.append(new_param('bs['+str(i)+']',hq[1:]))
                        fs.append(new_param('fs['+str(i)+']',-Gq[0,:].T))
                        ds.append(new_param('ds['+str(i)+']',hq[0]))
                        zs.append(dual.add_variable('zs['+str(i)+']',As[i].size[0]))
                        lbda.append(dual.add_variable('lbda['+str(i)+']',1))
                        dual.add_constraint(abs(zs[i])<lbda[i])
                        lincons += (As[i].T * zs[i]-fs[i]*lbda[i])
                        obj     += (bs[i].T * zs[i]-ds[i]*lbda[i])
                        i+=1
                #sdp cons
                j=0
                X = []
                M0 = []
                factors = {}
                for Gs,hs in zip(self.cvxoptVars['Gs'],self.cvxoptVars['hs']):
                        nbar = int(Gs.size[0]**0.5)
                        svecs = [svec(cvx.matrix(Gs[:,k],(nbar,nbar))).T for k in range(Gs.size[1])]
                        msvec = cvx.sparse(svecs)
                        X.append(dual.add_variable('X['+str(j)+']',(nbar,nbar),'symmetric'))
                        factors[X[j]] = -msvec
                        dual.add_constraint(X[j]>>0)
                        M0.append(new_param('M0['+str(j)+']',-cvx.matrix(hs,(nbar,nbar))))
                        obj += (M0[j] | X[j])
                        j+=1
                        
                        
                if factors:
                        maff=AffinExp(factors=factors,size=(msvec.size[0],1),string = 'M dot X')
                else:
                        maff = 0
                dual.add_constraint(lincons==maff)
                dual.set_objective('max',obj)
                dual._options=_NonWritableDict(self.options)
                #deactivate the solve_via_dual option (to avoid further dualization)
                dual.set_option('solve_via_dual', False)
                return dual

        """TODO primalize function (in development)
        def primalize(self):
                if self.numberLSEConstraints>0:
                        raise DualizationError('GP cannot be dualized by PICOS')
                if not self.is_continuous():
                        raise DualizationError('Mixed integer problems cannot be dualized by picos')
                if self.numberQuadConstraints>0:
                        raise QuadAsSocpError('try to convert the quads as socp before dualizing')
                
                #we first create a copy of the problem with the desired "nice dual form"
                pcop = self.copy()
                
                socones = [] #list of list of (var index,coef) in a so cone
                rscones = [] #list of list of (var index,coef) in a rotated so cone
                semidefs = [] #list of list of var indices in a sdcone
                semidefset = set([]) #set of var indices in a sdcone
                conevarset = set([]) #set of var indices in a (rotated) so cone
                indlmi = 0
                indzz= 0
                XX=[]
                zz=[]
                #add new variables for LMI
                listsdpcons = [(i,cons) for (i,cons) in enumerate(pcop.constraints) if cons.typeOfConstraint.startswith('sdp')]
                for (i,cons) in reversed(listsdpcons):
                        if cons.semidefVar:
                                var = cons.semidefVar
                                semidefs.append(range(var.startIndex,var.endIndex))
                                semidefset.update(range(var.startIndex,var.endIndex))
                        else:
                                sz = cons.Exp1.size
                                pcop.remove_constraint(i)
                                XX.append(pcop.add_variable('_Xlmi['+str(indlmi)+']',sz,'symmetric'))
                                pcop.add_constraint(XX[indlmi]>>0)
                                if cons.typeOfConstraint[3]=='<':
                                        pcop.add_constraint(lowtri(XX[indlmi]) == lowtri(cons.Exp2-cons.Exp1))
                                else:
                                        pcop.add_constraint(lowtri(XX[indlmi]) == lowtri(cons.Exp1-cons.Exp2))
                                semidefs.append(range(XX[indlmi].startIndex,XX[indlmi].endIndex))
                                semidefset.update(range(XX[indlmi].startIndex,XX[indlmi].endIndex))
                                indlmi+=1
                #add new variables for soc cones
                listconecons = [(idcons,cons) for (idcons,cons) in enumerate(pcop.constraints) if cons.typeOfConstraint.endswith('cone')]
                for (idcons,cons) in reversed(listconecons):
                        conexp = (cons.Exp2 // cons.Exp1[:])
                        if cons.Exp3:
                                conexp = ((cons.Exp3) // conexp)
                        
                        #parse the (i,j,v) triple
                        ijv=[]
                        for var,fact in conexp.factors.iteritems():
                                if type(fact)!=cvx.base.spmatrix:
                                        fact = cvx.sparse(fact)
                                sj = var.startIndex
                                ijv.extend(zip( fact.I, fact.J +sj,fact.V))
                        ijvs=sorted(ijv)
                        
                        itojv={}
                        lasti=-1
                        for (i,j,v) in ijvs:
                                if i==lasti:
                                        itojv[i].append((j,v))
                                else:
                                        lasti=i
                                        itojv[i]=[(j,v)]   
                        

                        szcons = conexp.size[0] * conexp.size[1]
                        rhstmp = conexp.constant
                        if rhstmp is None:
                                rhstmp = cvx.matrix(0.,(szcons,1))

                        newconexp = new_param(' ',cvx.matrix([]))
                        thiscone = []
                        oldcone = []
                        newvars = []
                        #find the vars which we can keep
                        for i in range(szcons):
                                jv = itojv.get(i,[])
                                if len(jv) == 1 and not(rhstmp[i]) and (jv[0][0] not in semidefset) and (jv[0][0] not in conevarset):
                                        conevarset.update([jv[0][0]])
                                        oldcone.append(jv[0])
                                else:
                                        newvars.append(i)
                                        
                        #add new vars
                        countnewvars = len(newvars)
                        if countnewvars>0:
                                zz.append(pcop.add_variable('_zz['+str(indzz)+']',countnewvars))
                                stz = zz[indzz].startIndex
                                indzz += 1
                                conevarset.update(range(stz,stz+countnewvars))
                                
                        
                        #construct the new variable, add (vars,coefs) in 'thiscone'
                        oldind = 0
                        newind = 0
                        for i in range(szcons):
                                jv = itojv.get(i,[])
                                if i not in newvars:
                                        newconexp //= conexp[i]
                                        thiscone.append(oldcone[oldind])
                                        oldind += 1
                                else:
                                        newconexp //= zz[-1][newind]
                                        thiscone.append((stz+newind,1))
                                        pcop.add_constraint(zz[-1][newind] == conexp[i])
                                        newind += 1
                        
                        if countnewvars>0:
                                pcop.remove_constraint(idcons)
                                if cons.Exp3:
                                        nwcons = abs(newconexp[2:])**2 < newconexp[0] * newconexp[1]
                                        if not(newvars in ([0],[1],[0,1])):
                                                ncstring = '||sub(x;_zz[{0}])||**2 < '.format(indzz-1)
                                        else:
                                                ncstring = '||' + cons.Exp1.string + '||**2 < '
                                        if 0 in newvars:
                                                ncstring += '_zz[{0}][0]'.format(indzz-1)
                                        else:
                                                ncstring += cons.Exp2.string
                                        if cons.Exp3.string !='1':
                                                if 1 in newvars:
                                                        if 0 in newvars:
                                                                ncstring += '* _zz[{0}][1]'.format(indzz-1)
                                                        else:
                                                                ncstring += '* _zz[{0}][0]'.format(indzz-1)
                                                else:
                                                        ncstring += '* '+cons.Exp3.string
                                        nwcons.myconstring = ncstring
                                        pcop.add_constraint(nwcons)
                                else:
                                        nwcons = abs(newconexp[1:]) < newconexp[0]
                                        if not(newvars==[0]):
                                                ncstring = '||sub(x;_zz[{0}])|| < '.format(indzz-1)
                                        else:
                                                ncstring = '||' + cons.Exp1.string + '|| < '
                                        if 0 in newvars:
                                                ncstring += '_zz[{0}][0]'.format(indzz-1)
                                        else:
                                                ncstring += cons.Exp2.string
                                        nwcons.myconstring = ncstring
                                        pcop.add_constraint(nwcons)
                        if cons.Exp3:
                                rscones.append(thiscone)
                        else:
                                socones.append(thiscone)
                                
                
                #TODO think about bounds
                return pcop #tmp return
                """
                
#----------------------------------------
#                 Obsolete functions
#----------------------------------------

        def set_varValue(self,name,value):
                self.set_var_value(name,value)
                
        def defaultOptions(self,**opt):
                self.set_all_options_to_default(opt)
                
        def set_options(self, **options):
                self.update_options( **options)

        def addConstraint(self,cons):
                self.add_constraint(cons)
       
        def isContinuous(self):
                return self.is_continuous()
                
        def makeCplex_Instance(self):
                self._make_cplex_instance()
                
        def makeCVXOPT_Instance(self):
                self._make_cvxopt_instance()
